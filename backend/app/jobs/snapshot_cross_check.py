"""`SnapshotCrossCheckJob` (S6 §6/§11) — periodic whole-book sweep half of ADR 6's tamper-detection
invariant. A `cross_check` failure must raise loudly (S6 §9 edge case 4), never be swallowed.
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
    """Admin/worker-role UoW for the sweep's own reads."""


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
