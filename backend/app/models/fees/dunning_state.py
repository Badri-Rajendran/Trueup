"""`dunning_state` (S10 §3.5, ADR 10) — one row per `fee_charge` currently being retried.

`customer_id` is denormalized (`approval_hold` precedent, S3 §3.3) so RLS can filter natively.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, Integer, event, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.fees._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class DunningStatus(StrEnum):
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"


class DunningState(Base):
    __tablename__ = "dunning_state"

    fee_charge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_charge.id"), primary_key=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[DunningStatus] = mapped_column(
        SQLAlchemyEnum(DunningStatus, name="dunning_status", values_callable=enum_values),
        nullable=False,
        default=DunningStatus.RETRYING,
        server_default=DunningStatus.RETRYING.value,
    )


event.listen(
    DunningState.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE dunning_state ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON dunning_state
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    DunningState.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON dunning_state;"
        "ALTER TABLE dunning_state DISABLE ROW LEVEL SECURITY;"
    ),
)


class DunningStateRepository(BaseRepository[DunningState]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=DunningState, customer_id_column=DunningState.customer_id)

    def get_by_fee_charge_id(self, fee_charge_id: uuid.UUID) -> DunningState | None:
        statement = self._tenant_scoped(
            select(DunningState).where(DunningState.fee_charge_id == fee_charge_id)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_customer(self, customer_id: uuid.UUID) -> list[DunningState]:
        statement = self._tenant_scoped(
            select(DunningState).where(DunningState.customer_id == customer_id)
        )
        return list(self.session.execute(statement).scalars().all())

    def list_due(self, *, now: datetime) -> list[DunningState]:
        """`DunningRetryJob`'s driver query (S10 §5); admin/worker-role, unscoped across customers."""
        statement = select(DunningState).where(
            DunningState.status == DunningStatus.RETRYING,
            DunningState.next_retry_at <= now,
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = ["DunningState", "DunningStateRepository", "DunningStatus"]
