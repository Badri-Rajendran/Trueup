"""Scheduler-free base class for advisory-lock-protected batch jobs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, Self

from sqlalchemy import text

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.models.ops import OpsUnitOfWork
from app.models.ops.job_run import JobCadence, JobRun, JobRunStatus

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType


class JobOutcome(StrEnum):
    COMPLETED = "completed"
    SKIPPED = "skipped"


class JobRunWriter(Protocol):
    def add_run(self, run: JobRun) -> None: ...


class JobUnitOfWork(Protocol):
    @property
    def job_runs(self) -> JobRunWriter: ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def try_advisory_lock(self, job_name: str) -> bool: ...

    def release_advisory_lock(self, job_name: str) -> None: ...

    def commit(self) -> None: ...


class ScheduledJobUnitOfWork(OpsUnitOfWork):
    """Worker-role UnitOfWork with explicit session-level advisory-lock helpers."""

    def try_advisory_lock(self, job_name: str) -> bool:
        return bool(
            self.session.execute(
                text("SELECT pg_try_advisory_lock(hashtext(:job_name))"), {"job_name": job_name}
            ).scalar_one()
        )

    def release_advisory_lock(self, job_name: str) -> None:
        self.session.execute(
            text("SELECT pg_advisory_unlock(hashtext(:job_name))"), {"job_name": job_name}
        )


def default_job_uow() -> JobUnitOfWork:
    return ScheduledJobUnitOfWork(
        customer_id=None,
        role=SessionRole.ADMIN,
        db_role=DbRole.WORKER,
    )


class ScheduledJob(ABC):
    """A plain job: Azure and the Flask CLI only invoke this same `run` method."""

    job_name: str
    cadence: JobCadence

    def __init__(
        self,
        *,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow_factory = uow_factory
        self._now = now

    def run(self, *, market_date: date) -> JobOutcome:
        with self._uow_factory() as uow:
            if not uow.try_advisory_lock(self.job_name):
                uow.commit()
                return JobOutcome.SKIPPED
            try:
                run = JobRun(job_name=self.job_name, cadence=self.cadence, market_date=market_date)
                uow.job_runs.add_run(run)
                self.perform()
                run.status = JobRunStatus.COMPLETED
                run.completed_at = self._now()
                uow.commit()
                return JobOutcome.COMPLETED
            except Exception as exc:
                run.status = JobRunStatus.FAILED
                run.completed_at = self._now()
                # Exception class preserves an operational signal without persisting provider data.
                run.error = type(exc).__name__
                uow.commit()
                raise
            finally:
                uow.release_advisory_lock(self.job_name)

    @abstractmethod
    def perform(self) -> None:
        """Execute the job's business operation. Subclasses import no scheduler."""
