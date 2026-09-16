"""`EventPublisher` (S12 §6, NFR-18) -- the only place a Pub/Sub channel string or the pushed
message shape is constructed. Callers publish through this, never `EventBusPort.publish` directly,
and always strictly after the triggering `uow.commit()` (S0 §5: no I/O inside a transaction) --
a dropped/never-open subscriber is not data loss, since nothing published here is ever the sole
record of a fact; the next plain `GET` still returns truth. Consistently with that, a publish
failure here is always best-effort: it is logged and swallowed, never propagated to the caller --
whose own commit has already succeeded and must not be undone (e.g. turned into a 500 that makes
Stripe retry an already-applied webhook) by a transient push-notification hiccup.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.integrations.ports import EventBusPort

log = get_logger(__name__)

ADVISER_CHANNEL = "adviser:events"


def customer_channel(customer_id: str) -> str:
    return f"customer:{customer_id}:events"


class EventPublisher:
    def __init__(self, bus: EventBusPort) -> None:
        self._bus = bus

    def order_updated(self, *, customer_id: str, order_id: str, summary: str) -> None:
        self._publish(
            customer_channel(customer_id),
            {"event_type": "order_updated", "entity_id": order_id, "summary": summary},
        )

    def identity_status_changed(
        self, *, customer_id: str, gate: Literal["kyc", "account_approval"], summary: str
    ) -> None:
        """The two gates publish independently -- never merged into one event -- so `event_type`
        itself encodes which gate changed."""
        self._publish(
            customer_channel(customer_id),
            {
                "event_type": f"{gate}_status_changed",
                "entity_id": customer_id,
                "summary": summary,
            },
        )

    def break_opened(self, *, break_id: str, summary: str) -> None:
        """Always the adviser channel, never a customer one -- a reconciliation break has no
        single-customer audience (S7 §5.2)."""
        self._publish(
            ADVISER_CHANNEL,
            {"event_type": "break_opened", "entity_id": break_id, "summary": summary},
        )

    def _publish(self, channel: str, message: dict[str, str]) -> None:
        """The one place that actually calls `EventBusPort.publish` -- every public method routes
        through here so the best-effort/non-fatal contract described in the module docstring holds
        for all three, not just whichever call site remembered to wrap it."""
        try:
            self._bus.publish(channel, message)
        except Exception:
            log.warning(
                "event_publish_failed",
                channel=channel,
                event_type=message.get("event_type"),
                exc_info=True,
            )


__all__ = ["ADVISER_CHANNEL", "EventPublisher", "customer_channel"]
