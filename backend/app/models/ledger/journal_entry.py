"""`journal_entry` (S1 §3.2) — the bitemporal unit of correction (ADR 1).

**Direction of `superseded_by`, resolved from two requirements that only admit one consistent
reading.** S1 §7 item 3 requires "a correction round-trip (`superseded_by` chain) leaves the
original row byte-for-byte unchanged" -- and `journal_entry` is append-only (no UPDATE grant,
`AppendOnlyViolationError` at the ORM layer), so the original row can never be mutated once
written. The only way both hold is for the **new, superseding** entry to carry
`superseded_by = <id of the entry it corrects>` -- never the other way around. This matches ADR
1's own wording: "A superseding posting links back to the one it corrects via `superseded_by`."
`JournalEntryRepository.is_superseded()` answers "has this entry since been corrected?" as the
reverse lookup this direction implies.
"""

from __future__ import annotations

import uuid
from datetime import (
    date,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    datetime,  # noqa: TC003
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, DateTime, ForeignKey, String, event, exists, func, select
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entry_type: Mapped[JournalEntryType] = mapped_column(
        SQLAlchemyEnum(JournalEntryType, name="journal_entry_type", values_callable=enum_values),
        nullable=False,
    )
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # See module docstring: set only on the *new*, superseding entry -- never written back onto
    # the entry it corrects.
    superseded_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=True
    )
    supersedes_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # Idempotency tie-in to intake (ADR 7's pattern, reused here, S1 §3.2): every journal entry
    # traces back to exactly one inbound_event, and every inbound_event produces at most one
    # journal entry.
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("inbound_event.id"), nullable=False, unique=True
    )
    memo: Mapped[str | None] = mapped_column(String, nullable=True)


# Append-only enforcement (S1 §6): no UPDATE/DELETE grant for either runtime credential, a hard
# DB-level guarantee bound to this table's own DDL lifecycle -- so a test fixture that creates
# `journal_entry` via SQLAlchemy metadata (rather than only via the Alembic migration) gets the
# real revocation too, same reasoning as the RLS policies in `account.py`/`posting.py`.
event.listen(
    JournalEntry.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON journal_entry FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class JournalEntryRepository(BaseRepository[JournalEntry]):
    """No `customer_id_column`: `journal_entry` carries no customer identity of its own (S1
    §3.2's schema has none) -- a single entry can span a customer's own accounts and a house
    account (e.g. a buy's fee leg). Per-customer reads go through `posting`, which does carry the
    denormalized `customer_id` (§3.3); this repository is for entry-level writes and the
    correction-chain lookup only, the same shape as `InboundEventRepository`/`JobOutboxRepository`
    (S0 ops-spine tables with no customer identity)."""

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
