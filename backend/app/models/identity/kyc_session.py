"""`kyc_session` (S2 §3.2, ADR 9) — one row per verification attempt.

Append-only per attempt; a resubmission opens a new row. `status` transitions exactly once,
`pending -> approved | rejected`, enforced by a `BEFORE UPDATE` trigger (S1 §6 single-transition pattern).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, Integer, String, event, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class KycSessionStatus(StrEnum):
    """Mapped from Stripe Identity's session statuses (ADR 9)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class KycSession(Base):
    __tablename__ = "kyc_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    provider_session_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[KycSessionStatus] = mapped_column(
        SQLAlchemyEnum(KycSessionStatus, name="kyc_session_status", values_callable=_enum_values),
        nullable=False,
        default=KycSessionStatus.PENDING,
        server_default=KycSessionStatus.PENDING.value,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default="now()"
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


_SINGLE_TRANSITION_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION kyc_session_single_transition() RETURNS trigger AS $$
    BEGIN
      IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'kyc_session %% is already terminal (%%) and cannot be updated',
          OLD.id, OLD.status;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_SINGLE_TRANSITION_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER kyc_session_before_update
      BEFORE UPDATE ON kyc_session
      FOR EACH ROW EXECUTE FUNCTION kyc_session_single_transition();
    """
)

for _ddl in (_SINGLE_TRANSITION_FUNCTION, _SINGLE_TRANSITION_TRIGGER):
    event.listen(KycSession.__table__, "after_create", _ddl)

event.listen(
    KycSession.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS kyc_session_before_update ON kyc_session;"
        "DROP FUNCTION IF EXISTS kyc_session_single_transition();"
    ),
)

# DELETE revoked (regulatory record); UPDATE stays granted for the one-time transition above.
event.listen(
    KycSession.__table__,
    "after_create",
    DDL("REVOKE DELETE ON kyc_session FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)

# RLS: role-aware tenant isolation (S0 §7.3, ADR 17).
event.listen(
    KycSession.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE kyc_session ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON kyc_session
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    KycSession.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON kyc_session;"
        "ALTER TABLE kyc_session DISABLE ROW LEVEL SECURITY;"
    ),
)


class KycSessionAlreadyResolvedError(RuntimeError):
    """Raised when a verdict is applied to a `kyc_session` row that is already terminal (S2 §4)."""


class SqlKycSessionRepository(BaseRepository[KycSession]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=KycSession, customer_id_column=KycSession.customer_id)

    def get_by_provider_session_id(self, provider_session_id: str) -> KycSession | None:
        statement = self._tenant_scoped(
            select(KycSession).where(KycSession.provider_session_id == provider_session_id)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_id(self, kyc_session_id: uuid.UUID) -> KycSession | None:
        statement = self._tenant_scoped(select(KycSession).where(KycSession.id == kyc_session_id))
        return self.session.execute(statement).scalar_one_or_none()

    def latest_for_customer(self, customer_id: uuid.UUID) -> KycSession | None:
        statement = self._tenant_scoped(
            select(KycSession)
            .where(KycSession.customer_id == customer_id)
            .order_by(KycSession.attempt_number.desc())
            .limit(1)
        )
        return self.session.execute(statement).scalar_one_or_none()

    @staticmethod
    def resolve(
        session_row: KycSession, *, status: KycSessionStatus, resolved_at: datetime
    ) -> None:
        if session_row.status is not KycSessionStatus.PENDING:
            raise KycSessionAlreadyResolvedError(
                f"kyc_session {session_row.id} is already {session_row.status}; "
                "status transitions exactly once (S2 §3.2)"
            )
        session_row.status = status
        session_row.resolved_at = resolved_at
