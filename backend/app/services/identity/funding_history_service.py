"""`FundingHistoryService` (S2 §6) -- `GET /api/v1/funding/history`'s read model.

Deposits and withdrawals only, most-recent-first, enriched with settlement status where one
exists. Reads `posting`/`journal_entry`/`account` directly, the same read-only join pattern
`CashPolicyService` and `app/services/valuation/history_service.py` already use over these tables.

Two deliberate shapes, both load-bearing:

- A bounced deposit's `correction` journal entry gets no row of its own. The deposit's own row's
  `settlement_status='failed'` plus `failure_reason` is the complete disclosure; a bounce is a
  status change on the SAME obligation, not a second event. `GET /valuation/history` still shows
  the raw correction entry for anyone reading the full ledger.
- A withdrawal has no `settlement_obligation` row at all, so its `settlement_status`,
  `expected_settlement_date`, and `failure_reason` are all `None` -- never a fabricated
  "settled"/"n/a" value, which would assert a custodial confirmation that never happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select, tuple_

from app.core.pagination import DEFAULT_PAGE_SIZE
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting

if TYPE_CHECKING:
    import uuid
    from datetime import date, datetime

    from app.core.money import Money
    from app.core.watermark import Watermark
    from app.models.ledger.settlement_obligation import SettlementObligationStatus
    from app.services.identity.funding_uow import FundingUnitOfWork


@dataclass(frozen=True, slots=True)
class FundingHistoryEntry:
    journal_entry_id: uuid.UUID
    entry_type: JournalEntryType
    effective_date: date
    recorded_at: datetime
    amount: Money
    settlement_status: SettlementObligationStatus | None
    expected_settlement_date: date | None
    failure_reason: str | None


class FundingHistoryService:
    def __init__(self, uow: FundingUnitOfWork) -> None:
        self._uow = uow

    def history(
        self,
        customer_id: uuid.UUID,
        *,
        as_of: Watermark,
        limit: int = DEFAULT_PAGE_SIZE,
        after: tuple[date, datetime, uuid.UUID] | None = None,
    ) -> list[FundingHistoryEntry]:
        """`Account.role == CASH` is not an optimization: every deposit/withdrawal entry has two
        legs (cash and equity) with opposite-sign amounts, so without it this returns two rows per
        journal entry and the signed `amount` becomes meaningless.

        Keyset-paginated on `(effective_date, recorded_at, journal_entry_id)` DESC (`GET
        /api/v1/funding/history`, S12 §8) -- the `journal_entry_id` tiebreak is required because
        two entries can share both dates. Fetches `limit + 1` rows; the caller applies
        `app.core.pagination.paginate()` to derive `next_cursor`."""
        statement = (
            select(JournalEntry, Posting)
            .join(Posting, Posting.journal_entry_id == JournalEntry.id)
            .join(Account, Account.id == Posting.account_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.CASH,
                JournalEntry.entry_type.in_(
                    (JournalEntryType.DEPOSIT, JournalEntryType.WITHDRAWAL)
                ),
                JournalEntry.recorded_at <= as_of.cutoff,
            )
        )
        if after is not None:
            after_effective_date, after_recorded_at, after_id = after
            statement = statement.where(
                tuple_(JournalEntry.effective_date, JournalEntry.recorded_at, JournalEntry.id)
                < (after_effective_date, after_recorded_at, after_id)
            )
        statement = statement.order_by(
            JournalEntry.effective_date.desc(),
            JournalEntry.recorded_at.desc(),
            JournalEntry.id.desc(),
        ).limit(limit + 1)
        rows = self._uow.session.execute(statement).all()

        obligations_by_entry = {
            obligation.journal_entry_id: obligation
            for obligation in self._uow.settlement_obligations.list_for_customer(customer_id)
        }

        entries: list[FundingHistoryEntry] = []
        for entry, posting in rows:
            obligation = obligations_by_entry.get(entry.id)
            entries.append(
                FundingHistoryEntry(
                    journal_entry_id=entry.id,
                    entry_type=entry.entry_type,
                    effective_date=entry.effective_date,
                    recorded_at=entry.recorded_at,
                    amount=posting.amount_money,
                    settlement_status=obligation.status if obligation is not None else None,
                    expected_settlement_date=(
                        obligation.expected_settlement_date if obligation is not None else None
                    ),
                    failure_reason=obligation.failure_reason if obligation is not None else None,
                )
            )
        return entries


__all__ = ["FundingHistoryEntry", "FundingHistoryService"]
