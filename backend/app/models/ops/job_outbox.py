"""Durable asynchronous work and its PostgreSQL locking repository."""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, Enum, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ops.inbound_event import _enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class JobOutboxStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    DEAD_LETTER = "dead_letter"


class JobOutbox(Base):
    __tablename__ = "job_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[JobOutboxStatus] = mapped_column(
        Enum(JobOutboxStatus, name="job_outbox_status", values_callable=_enum_values),
        nullable=False,
        default=JobOutboxStatus.PENDING,
        server_default=JobOutboxStatus.PENDING.value,
    )
    locked_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class JobOutboxRepository(BaseRepository[JobOutbox]):
    """One transactional owner for state transitions of durable asynchronous work."""

    def __init__(self, uow: UnitOfWork) -> None:
        # job_outbox is an internal operational table with no customer identity — no
        # customer_id_column to configure (see BaseRepository).
        super().__init__(uow, entity=JobOutbox)

    def enqueue(self, task: str, payload: dict[str, str]) -> JobOutbox:
        row = JobOutbox(task=task, payload=payload)
        self.add(row)
        return row

    def claim_next(self, *, worker_id: str, now: datetime) -> JobOutbox | None:
        statement = (
            select(JobOutbox)
            .where(
                JobOutbox.status == JobOutboxStatus.PENDING,
                JobOutbox.next_attempt_at <= now,
            )
            .order_by(JobOutbox.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is not None:
            row.status = JobOutboxStatus.PROCESSING
            row.locked_by = worker_id
            row.attempts += 1
        return row

    def complete(self, *, outbox_id: uuid.UUID, worker_id: str) -> None:
        row = self._locked_by_worker(outbox_id=outbox_id, worker_id=worker_id)
        row.status = JobOutboxStatus.COMPLETED
        row.locked_by = None

    def retry_or_dead_letter(
        self,
        *,
        outbox_id: uuid.UUID,
        worker_id: str,
        next_attempt_at: datetime,
        max_attempts: int,
    ) -> JobOutboxStatus:
        row = self._locked_by_worker(outbox_id=outbox_id, worker_id=worker_id)
        row.locked_by = None
        if row.attempts >= max_attempts:
            row.status = JobOutboxStatus.DEAD_LETTER
        else:
            row.status = JobOutboxStatus.PENDING
            row.next_attempt_at = next_attempt_at
        return row.status

    def _locked_by_worker(self, *, outbox_id: uuid.UUID, worker_id: str) -> JobOutbox:
        statement = select(JobOutbox).where(
            JobOutbox.id == outbox_id,
            JobOutbox.status == JobOutboxStatus.PROCESSING,
            JobOutbox.locked_by == worker_id,
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            raise RuntimeError("outbox row is not claimed by this worker")
        return row
