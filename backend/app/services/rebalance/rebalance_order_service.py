"""`RebalanceOrderService` (S9 §6) — turns a `DriftEvaluation`'s flagged entries into orders,
sells before buys, sized to close each holding's drift to zero (not to the band edge) and capped
by a cash buffer on the buy side.

Depends on two narrow `Protocol`s, `OrderPlacer`/`InvestableCashProvider`, rather than the concrete
`OrderService`/`CashPolicyService` directly (S0 §5's own precedent: "services depend on their
aggregate's own Protocol... a test substitutes a fake by implementing that Protocol structurally").
That is what makes S9 §9's unit-level tests -- sells-before-buys ordering, the cash-buffer sizing
arithmetic, the buffer-drives-a-buy-to-zero edge case (S9 §8 item 5) -- runnable with no database at
all; `_RealOrderPlacer` below is the thin adapter the job/controller wires the real `OrderService`
through.

No `designation_override` is ever passed (S5 §4/ADR 4: a system-generated sell always takes the
FIFO branch, since no investor is present to elect lots) -- this falls out for free, since
`OrderCreationRequest` (S3 §3.1) has no such field to begin with; there is nothing here that could
set one.

A rebalance order above `order_approval_threshold_usd` lands in `awaiting_approval` exactly like a
customer-placed order would (S9 §6: "identical to a customer order") -- this service only enqueues
broker submission when `OrderService.create_order` already auto-approved it; an
`awaiting_approval` rebalance order simply waits for the owning customer's own
`POST /orders/<id>/approve`, the same endpoint and the same state machine a customer-initiated
order above threshold already goes through. No second approval path is introduced for a
system-generated order.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.core.money import Money, Units
from app.models.orders.order import Order, OrderSide, OrderStatus
from app.services.orders.order_service import OrderCreationRequest

if TYPE_CHECKING:
    import uuid
    from decimal import Decimal

    from app.core.money import Price
    from app.services.orders.order_service import OrderService
    from app.services.rebalance.drift_evaluation_service import DriftEntry, DriftEvaluation


class OrderPlacer(Protocol):
    """The minimal surface `RebalanceOrderService` needs to place one order -- satisfied by
    `_RealOrderPlacer` (this module) in production, and by a plain recording fake in a unit test."""

    def place(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        side: OrderSide,
        quantity: Units,
        reference_price: Price,
    ) -> Order: ...


class InvestableCashProvider(Protocol):
    def investable(self, customer_id: uuid.UUID) -> Money: ...


class _RealOrderPlacer:
    """Adapter over the real `OrderService` (S3) -- `create_order` plus the same conditional
    `enqueue_submission` every customer-order controller route already applies (only when
    auto-approved; see this module's own docstring for the `awaiting_approval` case)."""

    def __init__(self, order_service: OrderService) -> None:
        self._order_service = order_service

    def place(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        side: OrderSide,
        quantity: Units,
        reference_price: Price,
    ) -> Order:
        order = self._order_service.create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=security_id,
                side=side,
                quantity=quantity,
                reference_price=reference_price,
            )
        )
        if order.status is OrderStatus.APPROVED:
            self._order_service.enqueue_submission(order)
        return order


def real_order_placer(order_service: OrderService) -> OrderPlacer:
    return _RealOrderPlacer(order_service)


class RebalanceOrderService:
    def __init__(
        self,
        *,
        order_placer: OrderPlacer,
        cash_provider: InvestableCashProvider,
        cash_buffer_pct: Decimal,
    ) -> None:
        self._order_placer = order_placer
        self._cash_provider = cash_provider
        self._cash_buffer_pct = cash_buffer_pct

    def generate_orders(self, evaluation: DriftEvaluation) -> list[Order]:
        """S9 §6's pseudocode exactly: sells first (never fund a buy from this run's own
        unsettled sell proceeds racing, S9 §6's own reasoning), then buys capped by the cash
        buffer. The implicit CASH entry (`security_id is None`) never itself produces an order --
        cash is not a tradeable security; its flag exists only for the admin visibility endpoint
        (`DriftEvaluationService`'s own docstring)."""
        security_flags = [entry for entry in evaluation.flagged if entry.security_id is not None]
        if not security_flags:
            return []

        orders: list[Order] = []
        for entry in security_flags:
            if entry.direction != "sell":
                continue
            orders.append(self._place_sell(evaluation.customer_id, entry))

        buy_entries = [entry for entry in security_flags if entry.direction == "buy"]
        if not buy_entries:
            return orders

        buffer = evaluation.total_value * self._cash_buffer_pct
        available = self._cash_provider.investable(evaluation.customer_id) - buffer
        if available <= Money("0.00"):
            # The buffer alone consumes all headroom -- S9 §8 item 5's documented outcome: a
            # smaller (here, zero) buy, never an error.
            return orders

        remaining = available
        for entry in buy_entries:
            if remaining <= Money("0.00"):
                break
            buy_notional = entry.target_market_value - entry.current_market_value
            capped_notional = buy_notional if buy_notional < remaining else remaining
            order = self._place_buy(evaluation.customer_id, entry, notional=capped_notional)
            if order is not None:
                orders.append(order)
                remaining -= capped_notional

        return orders

    def _place_sell(self, customer_id: uuid.UUID, entry: DriftEntry) -> Order:
        assert entry.security_id is not None  # narrowed by generate_orders' own filter
        assert entry.price is not None
        notional = entry.current_market_value - entry.target_market_value
        quantity = self._quantity_for(notional, entry.price)
        return self._order_placer.place(
            customer_id=customer_id,
            security_id=entry.security_id,
            side=OrderSide.SELL,
            quantity=quantity,
            reference_price=entry.price,
        )

    def _place_buy(
        self, customer_id: uuid.UUID, entry: DriftEntry, *, notional: Money
    ) -> Order | None:
        assert entry.security_id is not None
        assert entry.price is not None
        if notional <= Money("0.00"):
            return None
        quantity = self._quantity_for(notional, entry.price)
        if quantity == Units("0"):
            # S9 §8 item 5: a buffer- or cap-driven notional too small to round to a nonzero
            # fractional share (Units' six decimal places) -- a smaller trade, not an error.
            return None
        return self._order_placer.place(
            customer_id=customer_id,
            security_id=entry.security_id,
            side=OrderSide.BUY,
            quantity=quantity,
            reference_price=entry.price,
        )

    @staticmethod
    def _quantity_for(notional: Money, price: Price) -> Units:
        """S9 §5: "the exact fractional quantity needed to close the drift to zero... rounded to
        `Units`'s six decimal places" -- `notional / price`, quantized to 6dp by `Units.__init__`
        itself (ADR 16)."""
        return notional / price


__all__ = [
    "InvestableCashProvider",
    "OrderPlacer",
    "RebalanceOrderService",
    "real_order_placer",
]
