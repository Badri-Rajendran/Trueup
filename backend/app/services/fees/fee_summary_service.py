"""`FeeSummaryService` (S10 §7) — the single place that assembles a customer's fee/dunning read
model, so `GET /api/v1/fees` and `GET /api/v1/admin/customers/<id>/fees` (S8 §4 row 6) call the
same code path rather than two independently-implemented aggregations that could drift apart (the
same DRY/no-drift discipline S8 §6 edge case 4 states for balance, applied here to fees).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.money import Money

if TYPE_CHECKING:
    import uuid

    from app.models.fees.dunning_state import DunningState
    from app.models.fees.fee_charge import FeeCharge
    from app.models.fees.high_water_mark import HighWaterMark
    from app.services.fees.uow import FeesUnitOfWork


@dataclass(frozen=True, slots=True)
class FeeSummary:
    accrual_to_date: Money
    high_water_mark: HighWaterMark | None
    charges: list[FeeCharge]
    dunning: DunningState | None


class FeeSummaryService:
    def __init__(self, uow: FeesUnitOfWork) -> None:
        self._uow = uow

    def summarize(self, customer_id: uuid.UUID) -> FeeSummary:
        today = datetime.now(UTC).date()
        period_start = today.replace(day=1)
        open_period_accruals = self._uow.fee_accruals.list_for_period(
            customer_id, period_start=period_start, period_end=today
        )
        accrual_to_date = Money("0.00")
        for accrual in open_period_accruals:
            accrual_to_date += accrual.fee_amount

        hwm = self._uow.high_water_marks.get_by_customer(customer_id)
        charges = self._uow.fee_charges.list_for_customer(customer_id)
        dunning_states = self._uow.dunning_states.get_by_customer(customer_id)

        return FeeSummary(
            accrual_to_date=accrual_to_date,
            high_water_mark=hwm,
            charges=charges,
            dunning=dunning_states[0] if dunning_states else None,
        )


__all__ = ["FeeSummary", "FeeSummaryService"]
