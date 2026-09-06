"""`HighWaterMarkService` (S10 §3.2/§4, ADR 10, S10 §8 edge case 2) — tracks each customer's peak
in **TWR-adjusted** terms, never raw portfolio value directly.

**The single most consequential correctness requirement in S10** (the spec's own words): a customer
depositing cash mechanically raises their portfolio value, and that must never be mistaken for
investment gain. The fix is to compare against a "shadow NAV" -- the dollar value the customer's
*first* funded balance would be worth today if it had only ever moved with investment performance,
never with a deposit or withdrawal -- rather than the live, flow-inflated portfolio balance.

**Why this needs no new stored field beyond `high_water_mark.peak_value` (S10 §3.2's literal
schema).** `shadow_nav` reuses `TwrService.compute_twr` (S4, FR-17) end to end: `TwrService`'s own
per-sub-period return already excludes every flow by construction (`(end - begin - flow) / begin`),
so linking sub-period returns from a customer's very first funded day to today produces a cumulative
return figure that a deposit can never move. Multiplying that cumulative return onto the dollar
value of the customer's first funded day recovers a dollar-denominated "what would this be worth
today on performance alone" figure -- fully re-derivable from the ledger and `sub_period_return` on
every call, so `high_water_mark` only ever needs to persist the ratcheted peak itself, exactly as
S10 §3.2 describes it ("a cache, not a ledger... always re-derivable... if this row were ever
lost").

A pure deposit with zero market movement therefore contributes a `return_pct` of exactly zero for
the sub-period it lands in (proven by `TwrService._sub_period_return`'s own formula), so
`shadow_nav` does not move and `ratchet()` accrues nothing -- the property this sub-project's own
test suite (S10 §9) is built to prove with many randomized deposit/gain combinations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.money import Money
from app.models.fees.high_water_mark import HighWaterMark
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.services.valuation.twr_service import TwrService
from app.services.valuation.valuation_service import ValuationService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from datetime import date

    from app.services.fees.uow import FeesUnitOfWork

_EXTERNAL_FLOW_TYPES = (JournalEntryType.DEPOSIT, JournalEntryType.WITHDRAWAL)


class HighWaterMarkService:
    def __init__(
        self, uow: FeesUnitOfWork, *, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._uow = uow
        self._twr_service = TwrService(uow)
        self._valuation = ValuationService(uow)
        self._now = now

    def shadow_nav(self, customer_id: uuid.UUID, as_of_date: date) -> Money | None:
        """The TWR-adjusted dollar value driving the high-water-mark comparison (module
        docstring). `None` when the customer has never funded an account yet -- there is no basis
        to compound a return onto, and no fee can accrue before a first deposit exists."""
        first_flow_date = self._first_flow_date(customer_id)
        if first_flow_date is None or first_flow_date > as_of_date:
            return None

        base_value = self._valuation.value_book(customer_id, first_flow_date).total_value
        if base_value == Money("0.00"):
            return None

        if first_flow_date == as_of_date:
            cumulative_twr = Decimal("0")
        else:
            cumulative_twr = self._twr_service.compute_twr(
                customer_id, first_flow_date, as_of_date
            ).twr

        return base_value * (Decimal("1") + cumulative_twr)

    def get_or_create(
        self, customer_id: uuid.UUID, *, shadow_value: Money
    ) -> HighWaterMark:
        """S10 §4: "creates at first-ever value if absent" -- a brand-new high-water-mark starts
        pinned to today's shadow NAV, so the very first accrual day always yields zero gain
        (nothing to be "above" yet)."""
        existing = self._uow.high_water_marks.get_by_customer(customer_id)
        if existing is not None:
            return existing
        hwm = HighWaterMark(
            customer_id=customer_id, peak_value=shadow_value, updated_at=self._now()
        )
        self._uow.high_water_marks.add(hwm)
        self._uow.session.flush()
        return hwm

    def ratchet(self, hwm: HighWaterMark, *, shadow_value: Money) -> Money:
        """S10 §4's `gain_above_hwm = max(0, current_value - hwm.peak_value)`, written in terms of
        the TWR-adjusted `shadow_value` rather than raw portfolio value (S10 §8 edge case 2). The
        peak only ratchets **up**, on the value that actually generated this gain -- never down,
        and never on a value a deposit alone produced."""
        gain = shadow_value - hwm.peak_value
        if gain <= Money("0.00"):
            return Money("0.00")
        hwm.peak_value = shadow_value
        hwm.updated_at = self._now()
        return gain

    def _first_flow_date(self, customer_id: uuid.UUID) -> date | None:
        statement = (
            select(JournalEntry.effective_date)
            .join(Posting, Posting.journal_entry_id == JournalEntry.id)
            .where(
                Posting.customer_id == customer_id,
                JournalEntry.entry_type.in_(_EXTERNAL_FLOW_TYPES),
            )
            .order_by(JournalEntry.effective_date.asc())
            .limit(1)
        )
        return self._uow.session.execute(statement).scalar_one_or_none()


__all__ = ["HighWaterMarkService"]
