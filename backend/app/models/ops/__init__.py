"""Operational persistence aggregates used by intake, workers, and scheduled jobs."""

from __future__ import annotations

from functools import cached_property

from sqlalchemy import text

from app.core.uow import UnitOfWork
from app.models.ops.inbound_event import InboundEventRepository
from app.models.ops.job_outbox import JobOutboxRepository
from app.models.ops.job_run import JobRunRepository


class OpsUnitOfWork(UnitOfWork):
    """A UnitOfWork exposing the repositories owned by the operations aggregate."""

    @cached_property
    def inbound_events(self) -> InboundEventRepository:
        return InboundEventRepository(self)

    @cached_property
    def outbox(self) -> JobOutboxRepository:
        return JobOutboxRepository(self)

    @cached_property
    def job_runs(self) -> JobRunRepository:
        return JobRunRepository(self)

    def notify_outbox_ready(self) -> None:
        """Queue a Postgres notification in this transaction with the outbox insert."""
        self.session.execute(text("SELECT pg_notify('job_outbox_ready', 'ready')"))
