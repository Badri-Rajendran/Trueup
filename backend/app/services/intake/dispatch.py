"""`InboundEventDispatcher` — the composition point every source's inbound event flows through
after `EventIntakeService` hands it to the outbox (S0 §6).

`OutboxWorker` (`app/workers/outbox.py`, Wave 2) requires a concrete `OutboxTaskHandler`, but
nothing implemented one: S0 §6 says every source (KYC verdicts, Plaid events, Alpaca fills, and
whatever S5-S12 adds later) shares this exact hand-off, so the thing that reads an `inbound_event`
row's `.source` and routes to the right per-source service is inherently cross-track — it cannot
be owned by any single S-spec's file list without that spec silently taking ownership of every
other source too. Built here, once, as infrastructure (the same reasoning as `ports.py`),
independent of which per-source handlers exist yet.

**How a track registers a handler**: call `dispatcher.register(InboundEventSource.STRIPE,
your_handler)` wherever your service wiring happens. A handler receives the raw, still-JSON
`payload` dict exactly as `inbound_event.payload` stored it — parsing it into a typed model is the
handler's own job, the same way `EventIntakeService.intake()` already expects a caller-parsed
`IncomingEvent` on the way in.

**Not yet wired end-to-end**: no track's handlers are registered here, and no process constructs
an `OutboxWorker` with this dispatcher and actually runs it (Wave 2 built `OutboxWorker` itself,
fully tested standalone, but never stood it up as a live process either). Tracked as owed
operational work, not a Wave 4 blocker -- each track's own tests exercise `handle()` directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    import uuid

    from app.models.ops.inbound_event import InboundEventSource


class InboundEventFetcher(Protocol):
    """What the dispatcher needs from a UnitOfWork to resolve an event by id — narrower than
    `OpsUnitOfWork` itself, so a test can supply a minimal fake."""

    def get_by_id(self, event_id: uuid.UUID) -> Any: ...  # returns InboundEvent | None


class UnregisteredSourceError(RuntimeError):
    """Raised rather than silently dropping an event whose source has no registered handler --
    a source with no handler is a wiring gap, not a no-op."""


class InboundEventDispatcher:
    def __init__(self) -> None:
        self._handlers: dict[InboundEventSource, Any] = {}

    def register(
        self, source: InboundEventSource, handler: Any
    ) -> None:
        """`handler` is any callable of shape `(payload: dict[str, Any]) -> None`. Registering the
        same source twice replaces the previous handler rather than erroring -- re-registration
        happens naturally across test setup/teardown and hot-reload in development."""
        self._handlers[source] = handler

    def handle(self, *, task: str, payload: dict[str, Any], uow: InboundEventFetcher) -> None:
        """Matches `OutboxTaskHandler`'s shape (`app/workers/outbox.py`) plus one extra keyword
        (`uow`) needed to resolve the event row -- a caller wires this in via a small closure/
        partial when constructing the `OutboxWorker`, since `OutboxTaskHandler.handle` itself
        takes only `(task, payload)`.
        """
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
