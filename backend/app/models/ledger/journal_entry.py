"""`journal_entry` (S1 §3.2) — the bitemporal unit of correction (ADR 1).

`superseded_by` is set on the new, superseding entry, pointing back at the one it corrects (ADR 1);
the original row is never mutated (S1 §7 item 3).
"""

from __future__ import annotations

import uuid
from datetime import (
    date,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    datetime,  # noqa: TC003
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, DateTime, ForeignKey, Index, String, event, exists, func, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class JournalEntryType(StrEnum):
    TRADE_BUY = "trade_buy"
    TRADE_SELL = "trade_sell"
    DEPOSIT = "deposit"
    WITHDRAWAL = "withdrawal"
    DIVIDEND = "dividend"
    SPLIT = "split"
    FEE_ADJUSTMENT = "fee_adjustment"
    CORRECTION = "correction"
    WASH_SALE_ADJUSTMENT = "wash_sale_adjustment"


class JournalEntry(Base):
    __tablename__ = "journal_entry"
    __table_args__ = (
        # S12 §3: S1/ADR 1's bitemporal range queries filter/order by each independently.
        Index("ix_journal_entry_effective_date", "effective_date"),
        Index("ix_journal_entry_recorded_at", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_type: Mapped[JournalEntryType] = mapped_column(
        SQLAlchemyEnum(JournalEntryType, name="journal_entry_type", values_callable=enum_values),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Set only on the new, superseding entry (see module docstring).
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=True
    )
    supersedes_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # Idempotency tie-in to intake (ADR 7's pattern).
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_event.id"), nullable=False, unique=True
    )
    memo: Mapped[str | None] = mapped_column(String, nullable=True)


# Append-only enforcement (S1 §6): no UPDATE/DELETE grant for either runtime credential.
event.listen(
    JournalEntry.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON journal_entry FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class JournalEntryRepository(BaseRepository[JournalEntry]):
    """No `customer_id_column`: `journal_entry` carries no customer identity (S1 §3.2). Per-customer
    reads go through `posting`."""

    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=JournalEntry, recorded_at_column=JournalEntry.recorded_at)

    def get_by_id(self, entry_id: uuid.UUID) -> JournalEntry | None:
        return self.session.query(JournalEntry).filter_by(id=entry_id).first()

    def is_superseded(self, entry_id: uuid.UUID) -> bool:
        """True once some other entry's `superseded_by` points at `entry_id` (module docstring)."""
        statement = select(
            exists().where(JournalEntry.superseded_by == entry_id)
        )
        return bool(self.session.execute(statement).scalar_one())
