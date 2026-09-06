"""`MonthlyFeeChargeJob` (S10 §5, `monthly` cadence) — for each customer with `fee_accrual` rows in
the billing period, creates the period's pending `fee_charge` (persisting intent plus an outbox row,
never calling Stripe itself -- S0 §5's no-I/O-in-transaction rule; `FeeChargeOutboxHandler` makes
the actual provider call once this job's own transaction has committed).

**Billing period = the calendar month immediately before the day the job runs on**, matching the
standard "bill last month's activity" cadence a job scheduled for the 1st of each month implies;
S10's own spec does not pin down the exact day-of-month scheduling, only the `monthly` cadence
itself (foundation spec §9).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from app.config import get_settings
from app.core.db import DbRole
from app.core.uow import SessionRole
from app.jobs.base import JobOutcome, ScheduledJob, default_job_uow
from app.models.ops.job_run import JobCadence
from app.services.fees.fee_charge_service import FeeChargeService
from app.services.fees.uow import FeesUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.jobs.base import JobUnitOfWork


class _MonthlyFeeChargeWorkUnitOfWork(FeesUnitOfWork):
    """Admin/worker-role UoW for the job's own writes -- see module docstring's flagged gap."""


def _default_work_uow_factory() -> _MonthlyFeeChargeWorkUnitOfWork:
    return _MonthlyFeeChargeWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


def previous_month_bounds(market_date: date) -> tuple[date, date]:
    """The full calendar month immediately before `market_date`'s own month."""
    first_of_this_month = market_date.replace(day=1)
    period_end = first_of_this_month - timedelta(days=1)
    period_start = period_end.replace(day=1)
    return period_start, period_end


class MonthlyFeeChargeJob(ScheduledJob):
    job_name = "monthly_fee_charge"
    cadence = JobCadence.MONTHLY

    def __init__(
        self,
        *,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[
            [], _MonthlyFeeChargeWorkUnitOfWork
        ] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._work_uow_factory = work_uow_factory
        self._market_date: date | None = None

    def run(self, *, market_date: date) -> JobOutcome:
        self._market_date = market_date
        return super().run(market_date=market_date)

    def perform(self) -> None:
        if self._market_date is None:  # pragma: no cover - defensive; run() always sets it first
            raise RuntimeError("MonthlyFeeChargeJob.perform() called before run()")
        period_start, period_end = previous_month_bounds(self._market_date)
        settings = get_settings()

        with self._work_uow_factory() as uow:
            charge_service = FeeChargeService(
                uow, dunning_max_attempts=settings.dunning_max_attempts, now=self._now
            )
            customer_ids = uow.fee_accruals.list_customers_with_accruals_in_period(
                period_start=period_start, period_end=period_end
            )
            for customer_id in customer_ids:
                charge_service.create_pending_charge(
                    customer_id, period_start=period_start, period_end=period_end
                )
            uow.commit()


__all__ = ["MonthlyFeeChargeJob", "previous_month_bounds"]
