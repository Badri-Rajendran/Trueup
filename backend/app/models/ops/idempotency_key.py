"""PostgreSQL-backed client idempotency records."""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, DateTime, Integer, String, UniqueConstraint, event, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.idempotency import IdempotencyRecord
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class IdempotencyKey(Base):
    __tablename__ = "idempotency_key"
    __table_args__ = (
        UniqueConstraint("customer_id", "key", name="uq_idempotency_key_customer_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# I9 fix (S0 §10.1 audit): `idempotency_key` is tenant-scoped -- `response_body` caches a
# customer's own order/funding response, financial PII -- but was the only tenant-scoped table in
# the schema with no RLS policy at all, every one of its 23 siblings has one. Matches the
# standard `tenant_isolation` predicate exactly (S0 §7.3, ADR 17).
event.listen(
    IdempotencyKey.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON idempotency_key
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    IdempotencyKey.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON idempotency_key;"
        "ALTER TABLE idempotency_key DISABLE ROW LEVEL SECURITY;"
    ),
)


class IdempotencyKeyRepository(BaseRepository[IdempotencyKey]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=IdempotencyKey, customer_id_column=IdempotencyKey.customer_id)

    def find(self, *, customer_id: uuid.UUID, key: str) -> IdempotencyRecord | None:
        row = self.session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.customer_id == customer_id,
                IdempotencyKey.key == key,
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return IdempotencyRecord(
            customer_id=row.customer_id,
            key=row.key,
            request_hash=row.request_hash,
            response_status=row.response_status,
            response_body=row.response_body,
            created_at=row.created_at,
        )

    def save(self, record: IdempotencyRecord) -> None:
        self.add(
            IdempotencyKey(
                customer_id=record.customer_id,
                key=record.key,
                request_hash=record.request_hash,
                response_status=record.response_status,
                response_body=record.response_body,
                created_at=record.created_at,
            )
        )
