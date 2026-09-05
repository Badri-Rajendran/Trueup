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

from sqlalchemy import select

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


class HistoryService:
    def __init__(self, uow: ValuationUnitOfWork) -> None:
        self._uow = uow

    def history(self, customer_id: uuid.UUID, *, as_of: Watermark) -> list[HistoryEntry]:
        statement = (
            select(JournalEntry, Posting)
            .join(Posting, Posting.journal_entry_id == JournalEntry.id)
            .where(
                Posting.customer_id == customer_id,
                JournalEntry.recorded_at <= as_of.cutoff,
            )
            .order_by(JournalEntry.effective_date.desc(), JournalEntry.recorded_at.desc())
        )
        rows = self._uow.session.execute(statement).all()
        return [
            HistoryEntry(
                entry_type=entry.entry_type,
                effective_date=entry.effective_date,
                recorded_at=entry.recorded_at,
                amount_money=posting.amount_money,
                quantity_units=posting.quantity_units,
                memo=entry.memo,
            )
            for entry, posting in rows
        ]


__all__ = ["HistoryEntry", "HistoryService"]
