"""Inbound provider event persistence and deduplication."""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class InboundEventSource(StrEnum):
    ALPACA = "alpaca"
    PLAID = "plaid"
    STRIPE = "stripe"
    MARKETDATA = "marketdata"
    CUSTODIAN_FILE = "custodian_file"


class InboundEventStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    FAILED = "failed"
    UNMATCHED = "unmatched"


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class InboundEvent(Base):
    __tablename__ = "inbound_event"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id", name="uq_inbound_event_source_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[InboundEventSource] = mapped_column(
        Enum(InboundEventSource, name="inbound_event_source", values_callable=_enum_values),
        nullable=False,
    )
    source_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[InboundEventStatus] = mapped_column(
        Enum(InboundEventStatus, name="inbound_event_status", values_callable=_enum_values),
        nullable=False,
        default=InboundEventStatus.RECEIVED,
        server_default=InboundEventStatus.RECEIVED.value,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String, nullable=True)


class DuplicateInboundEventError(RuntimeError):
    """The provider event has already been durably accepted."""


class InboundEventRepository(BaseRepository[InboundEvent]):
    """Writes the unique provider identity that is the system's event dedupe key."""

    def __init__(self, uow: UnitOfWork) -> None:
        # inbound_event is an internal operational table with no customer identity — no
        # customer_id_column to configure (see BaseRepository).
        super().__init__(uow, entity=InboundEvent)

    def record(self, event: InboundEvent) -> None:
        try:
            # A savepoint confines a duplicate-key failure so the caller can acknowledge the replay
            # without discarding the surrounding transaction.
            with self.session.begin_nested():
                self.add(event)
                self.session.flush()
        except IntegrityError as exc:
            if getattr(exc.orig, "sqlstate", None) == "23505":
                raise DuplicateInboundEventError from exc
            raise

    def get_by_id(self, event_id: uuid.UUID) -> InboundEvent | None:
        """The outbox payload for `process_inbound_event` carries only the id (`event_intake.py`)
        -- this is how the dispatcher (`services/intake/dispatch.py`) resolves the row to read
        `.source`/`.payload` from."""
        return self.session.query(InboundEvent).filter_by(id=event_id).first()
