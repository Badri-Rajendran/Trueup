"""A concrete no-op proving the common scheduled-job entrypoint end to end."""

from __future__ import annotations

from app.jobs.base import ScheduledJob
from app.models.ops.job_run import JobCadence


class NoopJob(ScheduledJob):
    job_name = "noop"
    cadence = JobCadence.DAILY

    def perform(self) -> None:
        return None
