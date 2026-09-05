from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.ops.inbound_event import InboundEventSource
from app.services.intake.event_intake import (
    EventIntakeService,
    IncomingEvent,
    IntakeResult,
)


class _Verifier:
    def __init__(self, accepted: bool) -> None:
        self._accepted = accepted

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        return self._accepted


class _InboundEvents:
    def __init__(self, duplicate: bool = False) -> None:
        self.duplicate = duplicate
        self.created: list[Any] = []

    def record(self, event: Any) -> None:
        if self.duplicate:
            from app.models.ops.inbound_event import DuplicateInboundEventError

            raise DuplicateInboundEventError
        self.created.append(event)


class _Outbox:
    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    def enqueue(self, task: str, payload: dict[str, str]) -> None:
        self.enqueued.append((task, payload))


class _Uow:
    def __init__(self, duplicate: bool = False) -> None:
        self.inbound_events = _InboundEvents(duplicate)
        self.outbox = _Outbox()
        self.committed = False
        self.notified = False

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def notify_outbox_ready(self) -> None:
        self.notified = True

    def commit(self) -> None:
        self.committed = True


def _service(uow: _Uow) -> EventIntakeService:
    def factory() -> _Uow:
        return uow

    return EventIntakeService(factory, _Verifier(accepted=True))


def test_verified_event_is_durably_queued_before_the_service_returns() -> None:
    uow = _Uow()
    result = _service(uow).intake(
        IncomingEvent(
            source=InboundEventSource.ALPACA,
            source_event_id="fill-123",
            payload={"fill_id": "fill-123"},
        ),
        raw_payload=b'{"fill_id":"fill-123"}',
        signature="valid",
    )

    assert result is IntakeResult.ACCEPTED
    assert uow.committed is True
    assert uow.notified is True
    assert uow.outbox.enqueued == [
        ("process_inbound_event", {"inbound_event_id": str(uow.inbound_events.created[0].id)})
    ]


def test_duplicate_verified_event_is_acknowledged_without_enqueueing_again() -> None:
    uow = _Uow(duplicate=True)
    result = _service(uow).intake(
        IncomingEvent(
            source=InboundEventSource.STRIPE,
            source_event_id="evt_123",
            payload={"id": "evt_123"},
        ),
        raw_payload=b'{"id":"evt_123"}',
        signature="valid",
    )

    assert result is IntakeResult.DUPLICATE
    assert uow.outbox.enqueued == []
    assert uow.committed is True


def test_invalid_signature_is_rejected_before_any_database_work() -> None:
    uow = _Uow()
    service = EventIntakeService(lambda: uow, _Verifier(accepted=False))

    result = service.intake(
        IncomingEvent(
            source=InboundEventSource.PLAID,
            source_event_id="event-1",
            payload={"event": "event-1"},
        ),
        raw_payload=b'{"event":"event-1"}',
        signature="invalid",
    )

    assert result is IntakeResult.INVALID_SIGNATURE
    assert uow.inbound_events.created == []
    assert uow.committed is False


def test_event_envelope_rejects_non_object_payloads() -> None:
    with pytest.raises(ValidationError):
        IncomingEvent(
            source=InboundEventSource.PLAID,
            source_event_id="event-1",
            payload=["not", "an", "object"],
        )
