"""`restatement_event` (S6 §3.2) — the audit trail of *why* a period was recomputed.

Not required for correctness (the `sub_period_return` recomputation itself is what matters, S6
§3.2's own framing) -- required so a customer dispute or an adviser question ("why did my March
return change?") has a concrete, queryable answer. Append-only, same posture as every other
correction-trail table in this codebase.
"""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    date,
    datetime,
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date as SQLAlchemyDate
from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.restatement._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class RestatementTriggerType(StrEnum):
    CORRECTED_CLOSE = "corrected_close"
    LATE_DIVIDEND = "late_dividend"
    SPLIT = "split"
    WASH_SALE_ADJUSTMENT = "wash_sale_adjustment"
    MANUAL_CORRECTION = "manual_correction"


class RestatementEvent(Base):
    __tablename__ = "restatement_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    affected_period_start: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    affected_period_end: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    trigger_type: Mapped[RestatementTriggerType] = mapped_column(
        SQLAlchemyEnum(
            RestatementTriggerType, name="restatement_trigger_type", values_callable=enum_values
        ),
        nullable=False,
    )
    # FK -> inbound_event, matching S1's own idempotency tie-in (`journal_entry.source_event_id`):
    # every real trigger this spec wires (S6 §4) is a posting whose own `source_event_id` already
    # names the inbound_event that caused it -- `RestatementService.restate()` is called with that
    # same id, never a fresh one.
    trigger_source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_event.id"), nullable=False
    )
    recomputed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RestatementEventRepository(BaseRepository[RestatementEvent]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow, entity=RestatementEvent, customer_id_column=RestatementEvent.customer_id
        )


__all__ = ["RestatementEvent", "RestatementEventRepository", "RestatementTriggerType"]
