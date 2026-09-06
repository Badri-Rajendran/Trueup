"""Execution records and idempotency keys for scheduled jobs."""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    date,
    datetime,
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, DateTime, Enum, Index, String, Text, event, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ops.inbound_event import _enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class JobCadence(StrEnum):
    DAILY = "daily"
    MONTHLY = "monthly"
    CONTINUOUS = "continuous"


class JobRunStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class JobRun(Base):
    __tablename__ = "job_run"
    __table_args__ = (
        Index(
            "uq_job_run_daily_name_market_date",
            "job_name",
            "market_date",
            unique=True,
            postgresql_where=text("cadence = 'daily'"),
        ),
        Index(
            "uq_job_run_monthly_name_market_month",
            "job_name",
            text("job_run_month_start(market_date)"),
            unique=True,
            postgresql_where=text("cadence = 'monthly'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cadence: Mapped[JobCadence] = mapped_column(
        Enum(JobCadence, name="job_cadence", values_callable=_enum_values), nullable=False
    )
    market_date: Mapped[date] = mapped_column(Date, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[JobRunStatus] = mapped_column(
        Enum(JobRunStatus, name="job_run_status", values_callable=_enum_values),
        nullable=False,
        default=JobRunStatus.STARTED,
        server_default=JobRunStatus.STARTED.value,
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


# Postgres's date_trunc() is STABLE not IMMUTABLE, so it can't appear directly in the partial
# unique index above; this wrapper function is the standard fix.
event.listen(
    JobRun.__table__,
    "before_create",
    DDL(  # type: ignore[no-untyped-call]
        "CREATE OR REPLACE FUNCTION job_run_month_start(d date) RETURNS date AS $$ "
        "SELECT date_trunc('month', d)::date "
        "$$ LANGUAGE sql IMMUTABLE"
    ),
)


class JobRunRepository(BaseRepository[JobRun]):
    def __init__(self, uow: UnitOfWork) -> None:
        # job_run is an internal operational table with no customer identity — no
        # customer_id_column to configure (see BaseRepository).
        super().__init__(uow, entity=JobRun)

    def add_run(self, run: JobRun) -> None:
        self.add(run)
