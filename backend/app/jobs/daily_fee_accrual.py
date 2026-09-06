"""`DailyFeeAccrualJob` (S10 §4, `daily` cadence) — for each customer with an active model
assignment, accrues that day's performance-fee gain above their high-water-mark.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.config import get_settings
from app.core.db import DbRole
from app.core.logging import get_logger
from app.core.uow import SessionRole
from app.jobs.base import JobOutcome, ScheduledJob, default_job_uow
from app.models.ops.job_run import JobCadence
from app.models.rebalance import RebalanceModelsUnitOfWork
from app.services.fees.fee_accrual_service import FeeAccrualService
from app.services.fees.uow import FeesUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.jobs.base import JobUnitOfWork

log = get_logger(__name__)


class _DailyFeeAccrualWorkUnitOfWork(FeesUnitOfWork, RebalanceModelsUnitOfWork):
    """Admin/worker-role UoW for the job's own writes."""


def _default_work_uow_factory() -> _DailyFeeAccrualWorkUnitOfWork:
    return _DailyFeeAccrualWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


class DailyFeeAccrualJob(ScheduledJob):
    job_name = "daily_fee_accrual"
    cadence = JobCadence.DAILY

    def __init__(
        self,
        *,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[
            [], _DailyFeeAccrualWorkUnitOfWork
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
        if self._market_date is None:  # pragma: no cover - defensive
            raise RuntimeError("DailyFeeAccrualJob.perform() called before run()")
        accrual_date = self._market_date
        settings = get_settings()

        with self._work_uow_factory() as uow:
            accrual_service = FeeAccrualService(
                uow, fee_rate_pct=settings.fee_rate_pct, now=self._now
            )
            for assignment in uow.customer_model_assignments.list_all():
                result = accrual_service.accrue_for_customer(
                    assignment.customer_id, accrual_date
                )
                if result is None:
                    log.info(
                        "daily_fee_accrual.skipped",
                        customer_id=str(assignment.customer_id),
                        accrual_date=accrual_date.isoformat(),
                    )
            uow.commit()


__all__ = ["DailyFeeAccrualJob"]
