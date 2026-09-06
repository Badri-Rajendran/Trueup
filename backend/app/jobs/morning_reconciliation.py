"""`MorningReconciliationJob` (S7 §6) — fetches the day's custodian file set and runs
`ReconciliationService.run_morning_reconciliation` under the daily `job_run` cadence (§9)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.core.clock import MarketClock
from app.core.db import DbRole
from app.core.uow import SessionRole
from app.jobs.base import JobOutcome, ScheduledJob, default_job_uow
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.models.ops.job_run import JobCadence
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.services.reconciliation.uow import ReconciliationUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.integrations.ports import CustodianFilePort
    from app.jobs.base import JobUnitOfWork


class _MorningReconciliationWorkUnitOfWork(ReconciliationUnitOfWork):
    """Admin/worker-role UoW for the job's own writes."""


def _default_work_uow_factory() -> _MorningReconciliationWorkUnitOfWork:
    return _MorningReconciliationWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


class MorningReconciliationJob(ScheduledJob):
    job_name = "morning_reconciliation"
    cadence = JobCadence.DAILY

    def __init__(
        self,
        *,
        custodian_file_port: CustodianFilePort,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[
            [], _MorningReconciliationWorkUnitOfWork
        ] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._custodian_file_port = custodian_file_port
        self._work_uow_factory = work_uow_factory
        self._market_date: date | None = None

    def run(self, *, market_date: date) -> JobOutcome:
        self._market_date = market_date
        return super().run(market_date=market_date)

    def perform(self) -> None:
        if self._market_date is None:  # pragma: no cover - defensive
            raise RuntimeError("MorningReconciliationJob.perform() called before run()")
        market_date = self._market_date

        with self._work_uow_factory() as uow:
            market_clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
            file_set = self._custodian_file_port.fetch_files(market_date=market_date)
            service = ReconciliationService(uow, market_clock=market_clock, now=self._now)
            service.run_morning_reconciliation(market_date=market_date, file_set=file_set)
            uow.commit()


__all__ = ["MorningReconciliationJob"]
