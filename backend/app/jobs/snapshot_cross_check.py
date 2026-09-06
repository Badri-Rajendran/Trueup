"""`SnapshotCrossCheckJob` (S6 §6/§11) — the periodic sweep half of ADR 6's tamper-detection
invariant, independent of any restatement activity (`RestatementService.restate()` already runs
`cross_check` inline for whatever periods a given correction touches; this job is the standing,
whole-book check that nothing else has drifted).

Needs no `market_date` for its own logic (unlike `DailyValuationJob`) -- `perform()` takes none,
so no override of `run()` is needed here; the CLI/scheduler still supplies one purely to satisfy
`ScheduledJob.run()`'s interface and `job_run`'s per-day uniqueness bookkeeping (S0 §13).

**A `cross_check` failure must be loud (S6 §9 edge case 4), never a silently-caught, logged
exception.** Every snapshot is still checked in one sweep pass (so one tamper doesn't hide
another), but if any failed, `perform()` raises after the pass completes -- `ScheduledJob.run()`
(`app/jobs/base.py`) is what turns that into `JobRun.status = FAILED` and re-raises, the same loud
operational alert every other job failure in this codebase produces.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.jobs.base import ScheduledJob, default_job_uow
from app.models.ops.job_run import JobCadence
from app.services.restatement.snapshot_service import SnapshotCrossCheckFailedError, SnapshotService
from app.services.restatement.uow import RestatementUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.jobs.base import JobUnitOfWork


class _SnapshotCrossCheckWorkUnitOfWork(RestatementUnitOfWork):
    """Admin/worker-role UoW for the sweep's own reads -- matches `DailyValuationJob`'s own
    `_DailyValuationWorkUnitOfWork` precedent (`app/jobs/daily_valuation.py`)."""


def _default_work_uow_factory() -> _SnapshotCrossCheckWorkUnitOfWork:
    return _SnapshotCrossCheckWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


class SnapshotCrossCheckJob(ScheduledJob):
    job_name = "snapshot_cross_check_sweep"
    cadence = JobCadence.DAILY

    def __init__(
        self,
        *,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[
            [], _SnapshotCrossCheckWorkUnitOfWork
        ] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._work_uow_factory = work_uow_factory

    def perform(self) -> None:
        with self._work_uow_factory() as uow:
            snapshot_service = SnapshotService(uow)
            failures: list[str] = []
            for snapshot in uow.published_snapshots.list_all():
                try:
                    snapshot_service.cross_check(snapshot)
                except SnapshotCrossCheckFailedError as exc:
                    failures.append(str(exc))
            uow.commit()

        if failures:
            raise SnapshotCrossCheckFailedError(
                f"{len(failures)} published_snapshot(s) failed cross_check: " + "; ".join(failures)
            )


__all__ = ["SnapshotCrossCheckJob"]
