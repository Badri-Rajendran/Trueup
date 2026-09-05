"""`AlpacaTradeUpdateHandler` — the `InboundEventDispatcher` route for
`InboundEventSource.ALPACA` (S0 §6's shared dispatch; ADR 22).

Registered via `dispatcher.register(InboundEventSource.ALPACA, handler.handle)` at application
wiring time (`app/services/intake/dispatch.py`'s own module docstring names this as "not yet wired
end-to-end" -- each track's tests exercise `handle()` directly, matching that note; the actual
`dispatcher.register(...)` call is application-startup wiring, owned wherever the rest of that
wiring happens).

**A second, minimal validation model, not the one `TradeUpdatesConsumer` uses.** Reusing that one
directly would require this module (`app/services/`) to import
`app/integrations/alpaca/trade_updates_consumer.py`, which `.importlinter`'s
`services-use-ports-only` contract forbids outright (services reach providers only through
`Protocol`s in `ports.py`, never a concrete integration module). The payload already passed that
model's validation once, at intake (foundation spec §6) -- this smaller one exists only so a
malformed row surfaces a clear `ValidationError` here too, rather than a bare `KeyError` deep in
dict access.
"""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003 -- Pydantic resolves field annotations at class-build time
)
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from app.models.orders.order_event import OrderEvent, OrderEventType, seq_from_timestamp
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.order_projection_service import OrderProjectionService

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.services.orders.uow import OrdersUnitOfWork

_EVENT_TYPE_BY_ALPACA_EVENT: dict[str, OrderEventType] = {
    "new": OrderEventType.ACCEPTED,
    "fill": OrderEventType.FILL,
    "partial_fill": OrderEventType.FILL,
    "canceled": OrderEventType.CANCELED,
    "expired": OrderEventType.EXPIRED,
    "rejected": OrderEventType.REJECTED,
}
"""Mirrors `trade_updates_consumer._HANDLED_EVENTS`' mapping intent -- duplicated rather than
imported for the layering reason in the module docstring; see that module for the full rationale
(Alpaca's `new` vs this system's `accepted`, `fill`/`partial_fill` both collapsing to `FILL`)."""


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
    """No `order` row matches the incoming message's `client_order_id` -- foundation spec §10
    case 4's "event referencing an entity the system does not yet know about." Raised rather than
    silently dropped; the outbox worker's own retry-then-dead-letter (`app/workers/outbox.py`) is
    what "parked... surfaced for operator attention" resolves to here, since this handler has no
    other channel back to `inbound_event.status` (the dispatcher that calls it does, not this
    module -- see `app/services/intake/dispatch.py`, not this sub-project's file)."""


class AlpacaTradeUpdateHandler:
    def __init__(
        self,
        *,
        uow_factory: Callable[[], OrdersUnitOfWork],
        now: Callable[[], datetime],
    ) -> None:
        self._uow_factory = uow_factory
        self._now = now

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
            uow.commit()


__all__ = [
    "AlpacaTradeUpdateHandler",
    "OrderNotFoundForClientOrderIdError",
]
