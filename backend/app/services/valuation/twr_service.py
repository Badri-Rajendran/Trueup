"""`TwrService` (S4 §5) — ADR 3's time-weighted-return algorithm made concrete.

**Why `sub_period_return` is a stored row, not just an intermediate value (S4 §5).** ADR 3 claims a
corrected close only touches one sub-period's return; that is only literally true if recomputing an
*unaffected* sub-period reliably reproduces the exact figure already on record, so the geometric
product can re-link from stored rows instead of a full end-to-end recompute. `_sub_period_return`
below is where that holds: it always recomputes from the live ledger and the latest confirmed
closes, but only **writes a new row** when the recomputed figures actually differ from the latest
stored one for that exact `(customer_id, sub_period_start, sub_period_end)` key — an unaffected
sub-period recomputes to the identical figures and its stored row is left untouched (same `id`,
same `recorded_at`); a sub-period whose underlying close was corrected recomputes to a different
`return_pct` and gets a genuinely new row, per `sub_period_return`'s append-only, bitemporal
posture. This is what makes the restatement-composability property (S4 §5, S4 §9) actually true
rather than aspirational, without S4 needing to know *why* a close changed — S6 owns that trigger.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from itertools import pairwise
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.services.valuation.valuation_service import ValuationService

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.services.valuation.uow import ValuationUnitOfWork

_EXTERNAL_FLOW_TYPES = (JournalEntryType.DEPOSIT, JournalEntryType.WITHDRAWAL)
_RETURN_QUANTUM = Decimal(1).scaleb(-10)  # NUMERIC(18,10), matching sub_period_return.return_pct


@dataclass(frozen=True, slots=True)
class TwrResult:
    """S4 §5's linked figure plus the stored sub-periods it was built from — a restatement (S6)
    re-links from `sub_periods`, never recomputes this end-to-end."""

    twr: Decimal
    period_start: date
    period_end: date
    is_provisional: bool
    sub_periods: tuple[SubPeriodReturn, ...]


class TwrService:
    def __init__(self, uow: ValuationUnitOfWork) -> None:
        self._uow = uow
        self._valuation = ValuationService(uow)

    def compute_twr(
        self, customer_id: uuid.UUID, period_start: date, period_end: date
    ) -> TwrResult:
        boundaries = self._boundaries(customer_id, period_start, period_end)
        sub_periods: list[SubPeriodReturn] = []
        linked = Decimal("1")
        any_provisional = False

        for v_begin, v_end in pairwise(boundaries):
            row = self._sub_period_return(customer_id, v_begin, v_end)
            sub_periods.append(row)
            linked *= Decimal("1") + row.return_pct
            any_provisional = any_provisional or row.is_provisional

        twr = (linked - Decimal("1")).quantize(_RETURN_QUANTUM, rounding=ROUND_HALF_EVEN)
        return TwrResult(
            twr=twr,
            period_start=period_start,
            period_end=period_end,
            is_provisional=any_provisional,
            sub_periods=tuple(sub_periods),
        )

    def _boundaries(
        self, customer_id: uuid.UUID, period_start: date, period_end: date
    ) -> list[date]:
        """`[period_start] + flow dates + [period_end]`, deduplicated (S4 §8 case 2: two same-day
        flows produce one break, not two degenerate zero-length sub-periods)."""
        flow_dates = self._flow_dates(customer_id, period_start, period_end)
        return sorted({period_start, *flow_dates, period_end})

    def _flow_dates(
        self, customer_id: uuid.UUID, period_start: date, period_end: date
    ) -> set[date]:
        statement = (
            select(JournalEntry.effective_date)
            .join(Posting, Posting.journal_entry_id == JournalEntry.id)
            .where(
                Posting.customer_id == customer_id,
                JournalEntry.entry_type.in_(_EXTERNAL_FLOW_TYPES),
                JournalEntry.effective_date > period_start,
                JournalEntry.effective_date < period_end,
            )
            .distinct()
        )
        return set(self._uow.session.execute(statement).scalars().all())

    def _flow_amount_on(self, customer_id: uuid.UUID, effective_date: date) -> Money:
        statement = (
            select(func.coalesce(func.sum(Posting.amount_money), 0))
            .join(Account, Account.id == Posting.account_id)
            .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.CASH,
                JournalEntry.entry_type.in_(_EXTERNAL_FLOW_TYPES),
                JournalEntry.effective_date == effective_date,
            )
        )
        value = self._uow.session.execute(statement).scalar_one()
        return value if value is not None else Money("0.00")

    def _sub_period_return(
        self, customer_id: uuid.UUID, v_begin: date, v_end: date
    ) -> SubPeriodReturn:
        begin_valuation = self._valuation.value_book(customer_id, v_begin)
        end_valuation = self._valuation.value_book(customer_id, v_end)
        flow_amount = self._flow_amount_on(customer_id, v_end)
        is_provisional = (
            begin_valuation.completeness == "partial" or end_valuation.completeness == "partial"
        )

        if begin_valuation.total_value == Money("0.00"):
            # No base to divide by yet (e.g. before a customer's first deposit) — a zero base
            # contributes zero return by convention, same spirit as S4 §8 case 3.
            return_pct = Decimal("0").quantize(_RETURN_QUANTUM, rounding=ROUND_HALF_EVEN)
        else:
            raw = (
                end_valuation.total_value - begin_valuation.total_value - flow_amount
            ) / begin_valuation.total_value
            return_pct = raw.quantize(_RETURN_QUANTUM, rounding=ROUND_HALF_EVEN)

        existing = self._uow.sub_period_returns.latest_for_sub_period(
            customer_id=customer_id, sub_period_start=v_begin, sub_period_end=v_end
        )
        if existing is not None and (
            existing.return_pct == return_pct
            and existing.value_begin == begin_valuation.total_value
            and existing.value_end == end_valuation.total_value
            and existing.flow_amount == flow_amount
            and existing.is_provisional == is_provisional
        ):
            return existing

        row = SubPeriodReturn(
            customer_id=customer_id,
            sub_period_start=v_begin,
            sub_period_end=v_end,
            return_pct=return_pct,
            value_begin=begin_valuation.total_value,
            value_end=end_valuation.total_value,
            flow_amount=flow_amount,
            is_provisional=is_provisional,
        )
        self._uow.sub_period_returns.add(row)
        self._uow.session.flush()
        return row


__all__ = ["TwrResult", "TwrService"]
