from __future__ import annotations

from datetime import UTC, date, datetime

from app.jobs.base import JobOutcome
from app.jobs.noop import NoopJob
from app.models.ops.job_run import JobRun, JobRunStatus


class _JobRuns:
    def __init__(self) -> None:
        self.runs: list[JobRun] = []

    def add_run(self, run: JobRun) -> None:
        self.runs.append(run)


class _Uow:
    def __init__(self, lock_acquired: bool) -> None:
        self.job_runs = _JobRuns()
        self.lock_acquired = lock_acquired
        self.released = False
        self.committed = False

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def try_advisory_lock(self, job_name: str) -> bool:
        return self.lock_acquired

    def release_advisory_lock(self, job_name: str) -> None:
        self.released = True

    def commit(self) -> None:
        self.committed = True


def test_noop_job_records_a_completed_run_and_releases_its_lock() -> None:
    uow = _Uow(lock_acquired=True)
    job = NoopJob(uow_factory=lambda: uow, now=lambda: datetime(2026, 9, 5, tzinfo=UTC))

    assert job.run(market_date=date(2026, 9, 5)) is JobOutcome.COMPLETED
    assert uow.committed is True
    assert uow.released is True
    assert uow.job_runs.runs[0].status is JobRunStatus.COMPLETED


def test_job_noops_when_an_overlapping_execution_holds_the_lock() -> None:
    uow = _Uow(lock_acquired=False)
    job = NoopJob(uow_factory=lambda: uow, now=lambda: datetime(2026, 9, 5, tzinfo=UTC))

    assert job.run(market_date=date(2026, 9, 5)) is JobOutcome.SKIPPED
    assert uow.job_runs.runs == []
    assert uow.committed is True
