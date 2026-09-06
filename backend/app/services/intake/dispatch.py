"""Routes an `inbound_event` row to its source's registered handler after the outbox hands it off (S0 §6).

Not yet wired end-to-end: no track's handlers are registered here, and no process runs
an `OutboxWorker` with this dispatcher yet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import uuid

    from app.models.ops.inbound_event import InboundEventSource


class InboundEventFetcher(Protocol):
    """What the dispatcher needs from a UnitOfWork to resolve an event by id."""

    def get_by_id(self, event_id: uuid.UUID) -> Any: ...  # returns InboundEvent | None


class UnregisteredSourceError(RuntimeError):
    """Raised rather than silently dropping an event whose source has no registered handler."""


class InboundEventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[InboundEventSource, Any] = {}

    def register(
        self, source: InboundEventSource, handler: Any
    ) -> None:
        """`handler` is any callable of shape `(payload: dict[str, Any]) -> None`. Re-registering replaces."""
        self._handlers[source] = handler

    def handle(self, *, task: str, payload: dict[str, Any], uow: InboundEventFetcher) -> None:
        """Matches `OutboxTaskHandler`'s shape plus one extra keyword (`uow`) to resolve the event row."""
        if task != "process_inbound_event":
            raise UnregisteredSourceError(f"no dispatcher route for outbox task {task!r}")

        event_id = payload["inbound_event_id"]
        event = uow.get_by_id(event_id)
        if event is None:
            raise UnregisteredSourceError(
                f"inbound_event {event_id} referenced by an outbox row does not exist"
            )

        handler = self._handlers.get(event.source)
        if handler is None:
            raise UnregisteredSourceError(
                f"no handler registered for inbound_event.source={event.source!r}"
            )
        handler(event.payload)
