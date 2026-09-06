"""Order state machine: creation with FR-10's approval threshold, approval, broker submission (S3 §4/§6/§7).

`reference_price` is caller-supplied, used only in memory. `symbol` resolves from S5's
securities catalogue at enqueue time, never from the caller.
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
    from app.services.ledger.cash_policy_service import CashPolicyService
    from app.services.orders.approval_hold_service import ApprovalHoldService
    from app.services.orders.uow import OrdersUnitOfWork

_TO_PORT_SIDE: dict[OrderSide, PortOrderSide] = {
    OrderSide.BUY: PortOrderSide.BUY,
    OrderSide.SELL: PortOrderSide.SELL,
}


class CustomerNotEligibleError(RuntimeError):
    """KYC/account-approval gate not satisfied (S3 §7 case 2); `reason` names the specific gate."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"customer is not eligible to place or submit orders: {reason}")
        self.reason = reason


class InsufficientInvestableCashError(RuntimeError):
    """A buy's notional exceeds `CashPolicyService.investable` (S0 §10.1/ADR 5)."""

    def __init__(self, *, notional: Money, investable: Money) -> None:
        super().__init__(f"order notional {notional} exceeds investable cash {investable}")
        self.notional = notional
        self.investable = investable


class OrderNotFoundError(RuntimeError):
    pass


class SecurityNotFoundError(RuntimeError):
    """`order.security_id` names no row in the securities catalogue; defensive only."""


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
    """Used only to size the threshold check and the hold; never stored."""


class OrderService:
    def __init__(
        self,
        uow: OrdersUnitOfWork,
        *,
        hold_service: ApprovalHoldService,
        cash_policy: CashPolicyService,
        approval_threshold_usd: Money,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._hold_service = hold_service
        self._cash_policy = cash_policy
        self._approval_threshold_usd = approval_threshold_usd
        self._now = now

    def create_order(self, request: OrderCreationRequest) -> Order:
        """S3 §4's `draft -> awaiting_approval | approved` transition, plus the hold. Does not commit."""
        self._require_eligible_customer(request.customer_id)
        self._uow.cash_locks.acquire(request.customer_id)

        notional = request.reference_price * request.quantity
        if request.side is OrderSide.BUY:
            investable = self._cash_policy.investable(request.customer_id)
            if notional > investable:
                raise InsufficientInvestableCashError(notional=notional, investable=investable)

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
        self._uow.session.flush()  # order.id must exist before approval_hold's FK
        self._hold_service.open(
            order_id=order_id, customer_id=request.customer_id, amount_money=notional
        )
        return order

    def approve(self, order_id: uuid.UUID) -> Order:
        """S3 §4/§6: `awaiting_approval -> approved`, the customer's explicit FR-10 approval."""
        order = self._uow.orders.get_for_update(order_id)
        if order is None:
            raise OrderNotFoundError(f"no order found for id={order_id!r}")
        if order.status is not OrderStatus.AWAITING_APPROVAL:
            raise InvalidOrderTransitionError(order_id, from_status=order.status, action="approve")
        order.status = OrderStatus.APPROVED
        return order

    def enqueue_submission(self, order: Order) -> None:
        """Enqueues the broker-submission outbox task; resolves `symbol` from S5's securities catalogue."""
        security = self._uow.securities.get_by_id(order.security_id)
        if security is None:  # pragma: no cover - defensive
            raise SecurityNotFoundError(f"no security found for id={order.security_id!r}")
        self._uow.outbox.enqueue(
            "submit_order_to_broker", {"order_id": str(order.id), "symbol": security.symbol}
        )
        self._uow.notify_outbox_ready()

    def submit_to_broker(self, order_id: uuid.UUID, *, symbol: str, broker: BrokerPort) -> None:
        """The `submit_order_to_broker` outbox task's body (S3 §4, §7 case 2): re-checks eligibility first."""
        order = self._uow.orders.get_for_update(order_id)
        if order is None:
            return  # defensive only
        if order.status is not OrderStatus.APPROVED:
            return  # already submitted/terminal; a retried outbox attempt

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
        """An `order_event` this service itself originates: `submitted` or pre-submission `rejected`."""
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
    "SecurityNotFoundError",
]
