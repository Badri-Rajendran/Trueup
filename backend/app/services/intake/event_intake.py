"""Signature-gated, deduplicated external event intake."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, Self

from pydantic import BaseModel, ConfigDict, Field

from app.models.ops.inbound_event import (
    DuplicateInboundEventError,
    InboundEvent,
    InboundEventSource,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class SignatureVerifier(Protocol):
    def verify(self, *, payload: bytes, signature: str | None) -> bool: ...


class InboundEventWriter(Protocol):
    def record(self, event: InboundEvent) -> None: ...


class OutboxWriter(Protocol):
    def enqueue(self, task: str, payload: dict[str, str]) -> object: ...


class IntakeUnitOfWork(Protocol):
    """Shaped exactly like `app.jobs.base.JobUnitOfWork` (the same `UnitOfWork`-satisfying
    Protocol pattern, proven against a real `cached_property`-based repository and the real
    3-argument context-manager `__exit__`) so any concrete `UnitOfWork` subclass exposing
    `.inbound_events`/`.outbox` -- however it composes them -- satisfies this Protocol structurally,
    with no adapter class required."""

    @property
    def inbound_events(self) -> InboundEventWriter: ...

    @property
    def outbox(self) -> OutboxWriter: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def notify_outbox_ready(self) -> None: ...

    def commit(self) -> None: ...


class IncomingEvent(BaseModel):
    """The validated envelope permitted to enter application-service logic."""

    model_config = ConfigDict(extra="forbid")

    source: InboundEventSource
    source_event_id: str = Field(min_length=1, max_length=255)
    payload: dict[str, Any]


class IntakeResult(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    INVALID_SIGNATURE = "invalid_signature"


class EventIntakeService:
    """Persist an accepted signal and its outbox hand-off in one transaction."""

    def __init__(
        self, uow_factory: Callable[[], IntakeUnitOfWork], verifier: SignatureVerifier
    ) -> None:
        self._uow_factory = uow_factory
        self._verifier = verifier

    def intake(
        self,
        event: IncomingEvent,
        *,
        raw_payload: bytes,
        signature: str | None,
    ) -> IntakeResult:
        if not self._verifier.verify(payload=raw_payload, signature=signature):
            return IntakeResult.INVALID_SIGNATURE

        with self._uow_factory() as uow:
            inbound_event = InboundEvent(
                source=event.source,
                source_event_id=event.source_event_id,
                payload=event.payload,
                signature_verified=True,
            )
            try:
                uow.inbound_events.record(inbound_event)
            except DuplicateInboundEventError:
                uow.commit()
                return IntakeResult.DUPLICATE
            uow.outbox.enqueue(
                "process_inbound_event", {"inbound_event_id": str(inbound_event.id)}
            )
            uow.notify_outbox_ready()
            uow.commit()
        return IntakeResult.ACCEPTED
