"""`InboundEventDispatcher` route for `InboundEventSource.ALPACA` (S0 §6, ADR 22).

Validates independently of `TradeUpdatesConsumer` (import-linter forbids the cross-layer
import); a `fill`/`partial_fill` event also drives S5's `LotConsumptionService`.
"""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003 -- Pydantic resolves field annotations at class-build time
)
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from app.core.clock import MarketClock
from app.core.money import Price, Units
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.models.orders.order import OrderSide
from app.models.orders.order_event import OrderEvent, OrderEventType, seq_from_timestamp
from app.services.lots.lot_consumption_service import LotConsumptionService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.order_projection_service import OrderProjectionService

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.orders.order import Order
    from app.services.orders.uow import OrdersUnitOfWork

def _default_market_clock_factory(uow: OrdersUnitOfWork) -> MarketClock:
    return MarketClock(CachedTradingCalendar(uow.calendar_cache))

_EVENT_TYPE_BY_ALPACA_EVENT: dict[str, OrderEventType] = {
    "new": OrderEventType.ACCEPTED,
    "fill": OrderEventType.FILL,
    "partial_fill": OrderEventType.FILL,
    "canceled": OrderEventType.CANCELED,
    "expired": OrderEventType.EXPIRED,
    "rejected": OrderEventType.REJECTED,
}
"""Mirrors `trade_updates_consumer._HANDLED_EVENTS`; duplicated to respect the layering rule."""


class _AlpacaTradeUpdateOrder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    client_order_id: str


class _AlpacaTradeUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event: str
    execution_id: str | None = None
    order: _AlpacaTradeUpdateOrder
    timestamp: datetime
    price: str | None = None
    qty: str | None = None


class OrderNotFoundForClientOrderIdError(RuntimeError):
    """No `order` row matches the incoming `client_order_id` (foundation spec §10 case 4)."""


class InvalidFillPayloadError(RuntimeError):
    """A `fill`/`partial_fill` event arrived with no `execution_id`/`qty`/`price` -- a broker
    contract violation (ADR 7's dedupe key and S5's lot-opening/consumption both require all
    three), not a state this handler can proceed past."""


class AlpacaTradeUpdateHandler:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], OrdersUnitOfWork],
        now: Callable[[], datetime],
        market_clock_factory: Callable[[OrdersUnitOfWork], MarketClock] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._now = now
        self._market_clock_factory = market_clock_factory or _default_market_clock_factory

    def handle(self, payload: dict[str, Any]) -> None:
        message = _AlpacaTradeUpdatePayload.model_validate(payload)
        event_type = _EVENT_TYPE_BY_ALPACA_EVENT.get(message.event)
        if event_type is None:
            return  # not one of this system's tracked lifecycle transitions (module docstring)

        with self._uow_factory() as uow:
            found = uow.orders.get_by_client_order_id(message.order.client_order_id)
            if found is None:
                raise OrderNotFoundForClientOrderIdError(message.order.client_order_id)
            order = uow.orders.get_for_update(found.id)
            if order is None:  # pragma: no cover - found under the same tenant scope moments ago
                raise OrderNotFoundForClientOrderIdError(message.order.client_order_id)

            event_payload: dict[str, Any] = (
                {"quantity": message.qty, "price": message.price}
                if event_type is OrderEventType.FILL
                else dict(payload)
            )
            execution_id = message.execution_id if event_type is OrderEventType.FILL else None
            hold_service = ApprovalHoldService(uow)
            projection = OrderProjectionService(uow, hold_service=hold_service, now=self._now)
            projection.apply_new_event(
                order,
                OrderEvent(
                    order_id=order.id,
                    seq=seq_from_timestamp(message.timestamp),
                    event_type=event_type,
                    execution_id=execution_id,
                    payload=event_payload,
                    recorded_at=self._now(),
                ),
            )

            if event_type is OrderEventType.FILL:
                self._record_lot_fill(uow, order=order, execution_id=execution_id, message=message)

            uow.commit()

    def _record_lot_fill(
        self,
        uow: OrdersUnitOfWork,
        *,
        order: Order,
        execution_id: str | None,
        message: _AlpacaTradeUpdatePayload,
    ) -> None:
        """Opens a lot on a buy fill, consumes lots on a sell fill (module docstring; S5 §4)."""
        if execution_id is None or message.qty is None or message.price is None:
            raise InvalidFillPayloadError(
                f"fill event for order {order.id} is missing execution_id/qty/price"
            )

        lot_service = LotConsumptionService(
            uow, market_clock=self._market_clock_factory(uow)
        )
        quantity = Units(message.qty)
        price = Price(message.price)
        if order.side is OrderSide.BUY:
            lot_service.record_buy_fill(
                customer_id=order.customer_id,
                security_id=order.security_id,
                execution_id=execution_id,
                quantity=quantity,
                price=price,
                filled_at=message.timestamp,
            )
        else:
            lot_service.record_sell_fill(
                customer_id=order.customer_id,
                security_id=order.security_id,
                execution_id=execution_id,
                quantity=quantity,
                price=price,
                filled_at=message.timestamp,
            )


__all__ = [
    "AlpacaTradeUpdateHandler",
    "InvalidFillPayloadError",
    "OrderNotFoundForClientOrderIdError",
]
