"""`HistoryService` (S4 §7's `GET /api/v1/valuation/history`) — reads S1's ledger directly.

S1 has no HTTP surface of its own (its spec's §2 non-goal), so S4 is the first consumer to expose
ledger history to a customer. This reads `posting`/`journal_entry` directly rather than adding a
method to either's repository — both are explicitly out of this task's files to touch — the same
read-only join pattern `CashPolicyService` already uses over the same two tables.

Defaults to live (ADR 6): every row with `journal_entry.recorded_at <= watermark.cutoff` is
visible, so a `Watermark.live()` caller sees every correction posted so far. S6 owns the
as-published variant (S4 §7).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, tuple_

from app.core.pagination import DEFAULT_PAGE_SIZE
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting

if TYPE_CHECKING:
    import uuid
    from datetime import date, datetime

    from app.core.money import Money, Units
    from app.core.watermark import Watermark
    from app.services.valuation.uow import ValuationUnitOfWork


@dataclass(frozen=True, slots=True)
class HistoryEntry:
    entry_type: JournalEntryType
    effective_date: date
    recorded_at: datetime
    amount_money: Money | None
    quantity_units: Units | None
    memo: str | None
    posting_id: uuid.UUID
    """Not surfaced in `HistoryEntryResponse` -- exists only as the cursor's third sort-key
    component (S12 §8's `(effective_date, recorded_at, posting_id)`); the cursor is opaque, so a
    field absent from the response body is fine there."""


class HistoryService:
    def __init__(self, uow: ValuationUnitOfWork) -> None:
        self._uow = uow

    def history(
        self,
        customer_id: uuid.UUID,
        *,
        as_of: Watermark,
        limit: int = DEFAULT_PAGE_SIZE,
        after: tuple[date, datetime, uuid.UUID] | None = None,
    ) -> list[HistoryEntry]:
        """Keyset-paginated on `(effective_date, recorded_at, posting_id)` DESC -- `posting_id`
        breaks ties between a journal entry's own legs, which otherwise share both dates. Fetches
        `limit + 1` rows; the caller applies `app.core.pagination.paginate()`."""
        statement = select(JournalEntry, Posting).join(
            Posting, Posting.journal_entry_id == JournalEntry.id
        ).where(
            Posting.customer_id == customer_id,
            JournalEntry.recorded_at <= as_of.cutoff,
        )
        if after is not None:
            after_effective_date, after_recorded_at, after_posting_id = after
            statement = statement.where(
                tuple_(JournalEntry.effective_date, JournalEntry.recorded_at, Posting.id)
                < (after_effective_date, after_recorded_at, after_posting_id)
            )
        statement = statement.order_by(
            JournalEntry.effective_date.desc(), JournalEntry.recorded_at.desc(), Posting.id.desc()
        ).limit(limit + 1)
        rows = self._uow.session.execute(statement).all()
        return [
            HistoryEntry(
                entry_type=entry.entry_type,
                effective_date=entry.effective_date,
                recorded_at=entry.recorded_at,
                amount_money=posting.amount_money,
                quantity_units=posting.quantity_units,
                memo=entry.memo,
                posting_id=posting.id,
            )
            for entry, posting in rows
        ]


__all__ = ["HistoryEntry", "HistoryService"]
