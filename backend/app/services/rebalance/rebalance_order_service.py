"""Turns a `DriftEvaluation`'s flagged entries into orders, sells before buys, capped by a
cash buffer (S9 §6).

Depends on narrow `OrderPlacer`/`InvestableCashProvider` `Protocol`s rather than the concrete
services, so S9 §9's unit tests run with no database.
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
    """The minimal surface `RebalanceOrderService` needs to place one order."""

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
    """Adapter over the real `OrderService` (S3): `create_order` plus conditional
    `enqueue_submission`."""

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
        """S9 §6: sells first, then buys capped by the cash buffer. CASH entries never produce
        an order."""
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
            # The buffer alone consumes all headroom (S9 §8 item 5): a zero buy, never an error.
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
            # Notional too small to round to a nonzero fractional share (S9 §8 item 5).
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
        """S9 §5: `notional / price`, quantized to 6dp by `Units.__init__` (ADR 16)."""
        return notional / price


__all__ = [
    "InvestableCashProvider",
    "OrderPlacer",
    "RebalanceOrderService",
    "real_order_placer",
]
