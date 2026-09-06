"""Tracks each customer's peak in TWR-adjusted terms, never raw portfolio value (S10 §3.2/§4, ADR 10).

Compares against a "shadow NAV" derived via `TwrService.compute_twr` so a deposit/withdrawal is
never mistaken for investment gain (S10 §8 edge case 2).
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
        """TWR-adjusted dollar value driving the HWM comparison. `None` if never funded."""
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
        """S10 §4: creates at first-ever value if absent, pinned to today's shadow NAV."""
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
        """S10 §4: `gain_above_hwm = max(0, shadow_value - hwm.peak_value)`; peak only ratchets up."""
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
