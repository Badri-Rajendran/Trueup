"""`OrderService` (S3 §4/§6/§7) — the order state machine: creation with the FR-10 approval
threshold, explicit customer approval, and broker submission with S3 §7 case 2's re-check.

**`OrderCreationRequest.reference_price` is a judgment call worth a second look** (flagged in this
sub-project's escalation, not yet resolved as of this writing): `order`'s schema (S3 §3.1) has no
price field, but both the FR-10 threshold check and `approval_hold.amount_money` (S3 §3.3) need a
dollar notional before any fill exists. This service takes that price from the caller rather than
reaching for a market-data dependency S3 doesn't otherwise have (`ports.py`'s `MarketDataPort` is
S4's) — every real caller already has one in hand: a customer's order-entry screen necessarily
shows a price, and S9's `RebalanceOrderService` already has one from S4's valuation to size
`quantity` in the first place. Used only in memory, never persisted on `order`.

**`symbol` travels through the outbox payload, not a new `order` column**, for the same reason:
`order.security_id` has no securities catalogue to resolve against yet (S5's to define,
`Account.security_id`'s own precedent, S1 §3.1) — see `enqueue_submission`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.money import Units
from app.integrations.ports import BrokerOrderHandle
from app.integrations.ports import OrderSide as PortOrderSide
from app.models.identity.customer import AccountApprovalStatus, KycStatus
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType, seq_from_timestamp
from app.services.orders.order_projection_service import OrderProjectionService

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.money import Money, Price
    from app.integrations.ports import BrokerPort
    from app.services.orders.approval_hold_service import ApprovalHoldService
    from app.services.orders.uow import OrdersUnitOfWork

_TO_PORT_SIDE: dict[OrderSide, PortOrderSide] = {
    OrderSide.BUY: PortOrderSide.BUY,
    OrderSide.SELL: PortOrderSide.SELL,
}


class CustomerNotEligibleError(RuntimeError):
    """KYC/account-approval gate not satisfied (S2 dependency; S3 §7 case 2). `reason` names the
    specific gate, matching `DepositService.FundingNotEligibleError`'s own shape (S2)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"customer is not eligible to place or submit orders: {reason}")
        self.reason = reason


class OrderNotFoundError(RuntimeError):
    pass


class InvalidOrderTransitionError(RuntimeError):
    def __init__(self, order_id: uuid.UUID, *, from_status: OrderStatus, action: str) -> None:
        super().__init__(
            f"order {order_id} cannot {action} from status {from_status.value!r}"
        )


@dataclass(frozen=True, slots=True)
class OrderCreationRequest:
    customer_id: uuid.UUID
    security_id: uuid.UUID
    side: OrderSide
    quantity: Units
    reference_price: Price
    """See module docstring -- used only to size the threshold check and the hold, never stored."""


class OrderService:
    def __init__(
        self,
        uow: OrdersUnitOfWork,
        *,
        hold_service: ApprovalHoldService,
        approval_threshold_usd: Money,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._hold_service = hold_service
        self._approval_threshold_usd = approval_threshold_usd
        self._now = now

    def create_order(self, request: OrderCreationRequest) -> Order:
        """S3 §4's `draft -> awaiting_approval | approved` transition, plus the hold both
        branches need (S3 §4's last paragraph: `awaiting_approval` and `approved`-not-yet-
        `submitted` both hold). Acquires the per-customer cash lock first (foundation spec §10
        case 1). Does not commit -- the caller's transaction boundary decides that."""
        self._require_eligible_customer(request.customer_id)
        self._uow.cash_locks.acquire(request.customer_id)

        notional = request.reference_price * request.quantity
        status = (
            OrderStatus.AWAITING_APPROVAL
            if notional > self._approval_threshold_usd
            else OrderStatus.APPROVED
        )
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=request.customer_id,
            security_id=request.security_id,
            side=request.side,
            quantity_requested=request.quantity,
            status=status,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        self._uow.orders.add(order)
        self._uow.session.flush()  # order.id must exist in the database before approval_hold's FK
        self._hold_service.open(
            order_id=order_id, customer_id=request.customer_id, amount_money=notional
        )
        return order

    def approve(self, order_id: uuid.UUID) -> Order:
        """S3 §4/§6: `awaiting_approval -> approved`, the customer's explicit FR-10 approval.
        Ownership/authentication is the controller's job (`@requires_ownership`); this method
        only enforces the state-machine transition itself."""
        order = self._uow.orders.get_for_update(order_id)
        if order is None:
            raise OrderNotFoundError(f"no order found for id={order_id!r}")
        if order.status is not OrderStatus.AWAITING_APPROVAL:
            raise InvalidOrderTransitionError(order_id, from_status=order.status, action="approve")
        order.status = OrderStatus.APPROVED
        return order

    def enqueue_submission(self, order: Order, *, symbol: str) -> None:
        """Enqueues the outbox task that actually calls the broker -- `submitted` only fires once
        that call succeeds (S3 §4), never at the moment this intent is persisted."""
        self._uow.outbox.enqueue(
            "submit_order_to_broker", {"order_id": str(order.id), "symbol": symbol}
        )
        self._uow.notify_outbox_ready()

    def submit_to_broker(self, order_id: uuid.UUID, *, symbol: str, broker: BrokerPort) -> None:
        """The `submit_order_to_broker` outbox task's body (S3 §4, §7 case 2): re-checks
        eligibility immediately before the broker call, since an account can be suspended between
        order creation and this later, asynchronous step. A gate that has closed blocks
        submission and rejects the order (releasing its hold with reason `rejected`) rather than
        placing an order for a customer no longer eligible to trade."""
        order = self._uow.orders.get_for_update(order_id)
        if order is None:
            return  # nothing to do -- should not happen, defensive only
        if order.status is not OrderStatus.APPROVED:
            return  # already submitted/terminal -- a retried outbox attempt after a partial success

        try:
            self._require_eligible_customer(order.customer_id)
        except CustomerNotEligibleError as exc:
            self._synthesize_event(
                order, OrderEventType.REJECTED, payload={"reason": exc.reason}
            )
            return

        handle: BrokerOrderHandle = broker.submit_order(
            client_order_id=order.client_order_id,
            symbol=symbol,
            side=_TO_PORT_SIDE[order.side],
            quantity=str(order.quantity_requested),
        )
        self._synthesize_event(
            order,
            OrderEventType.SUBMITTED,
            payload={"broker_order_id": handle.broker_order_id},
        )

    # --- internals --------------------------------------------------------------------------

    def _synthesize_event(
        self, order: Order, event_type: OrderEventType, *, payload: dict[str, Any]
    ) -> None:
        """An `order_event` this service itself originates, not a broker-delivered one: the
        `submitted` event on broker success, and the pre-submission `rejected` event when case 2's
        re-check fails. Shares `seq_from_timestamp` with every other `order_event` writer
        (`app.models.orders.order_event`'s own docstring) -- one ordering mechanism regardless of
        source."""
        projection = OrderProjectionService(
            self._uow, hold_service=self._hold_service, now=self._now
        )
        projection.apply_new_event(
            order,
            OrderEvent(
                order_id=order.id,
                seq=seq_from_timestamp(self._now()),
                event_type=event_type,
                payload=payload,
                recorded_at=self._now(),
            ),
        )

    def _require_eligible_customer(self, customer_id: uuid.UUID) -> None:
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotEligibleError("customer_not_found")
        if customer.kyc_status is not KycStatus.approved:
            raise CustomerNotEligibleError(f"kyc_status_{customer.kyc_status.value}")
        if customer.account_approval_status is not AccountApprovalStatus.approved:
            raise CustomerNotEligibleError(
                f"account_approval_status_{customer.account_approval_status.value}"
            )


__all__ = [
    "CustomerNotEligibleError",
    "InvalidOrderTransitionError",
    "OrderCreationRequest",
    "OrderNotFoundError",
    "OrderService",
]
