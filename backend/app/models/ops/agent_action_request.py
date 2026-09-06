"""`agent_action_request` (S13 §3.1, ADR 24) — one row per MCP write-tool proposal.

Two-hop transition graph: `pending -> {approved, rejected}`, then `approved -> {executed,
execution_failed}`, enforced by a `BEFORE UPDATE` trigger (extends `reconciliation_break`'s
pattern).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, CheckConstraint, DateTime, Index, String, event, func, select, tuple_
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class AgentActionType(StrEnum):
    RESOLVE_BREAK = "resolve_break"
    KYC_OVERRIDE = "kyc_override"
    REBALANCE = "rebalance"


class AgentActionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    EXECUTION_FAILED = "execution_failed"


class AgentActionRequest(Base):
    __tablename__ = "agent_action_request"
    __table_args__ = (
        CheckConstraint(
            "(status NOT IN ('approved','rejected')) "
            "OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL)",
            name="review_requires_reviewer",
        ),
        CheckConstraint(
            "(status <> 'executed') OR (executed_at IS NOT NULL)",
            name="executed_requires_timestamp",
        ),
        CheckConstraint(
            "(status <> 'execution_failed') OR (execution_error IS NOT NULL)",
            name="failure_requires_error",
        ),
        CheckConstraint(
            "length(justification) > 0", name="justification_present"
        ),
        Index("ix_agent_action_request_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    action: Mapped[AgentActionType] = mapped_column(
        SQLAlchemyEnum(AgentActionType, name="agent_action_type", values_callable=_enum_values),
        nullable=False,
    )
    arguments: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    requesting_agent: Mapped[str] = mapped_column(String, nullable=False)
    justification: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[AgentActionStatus] = mapped_column(
        SQLAlchemyEnum(AgentActionStatus, name="agent_action_status", values_callable=_enum_values),
        nullable=False,
        default=AgentActionStatus.PENDING,
        server_default=AgentActionStatus.PENDING.value,
    )
    # No FK: predates a formal cross-schema FK convention (matches
    # reconciliation_break.resolved_by).
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String, nullable=True)
    execution_error: Mapped[str | None] = mapped_column(String, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_SINGLE_TRANSITION_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION agent_action_request_single_transition() RETURNS trigger AS $$
    BEGIN
      IF OLD.status = 'pending' THEN
        IF NEW.status NOT IN ('approved', 'rejected') THEN
          RAISE EXCEPTION
            'agent_action_request %% may only move from pending to approved or rejected (got %%)',
            OLD.id, NEW.status;
        END IF;
      ELSIF OLD.status = 'approved' THEN
        IF NEW.status NOT IN ('executed', 'execution_failed') THEN
          RAISE EXCEPTION
            'agent_action_request %% may only move approved -> executed/execution_failed (got %%)',
            OLD.id, NEW.status;
        END IF;
      ELSE
        RAISE EXCEPTION 'agent_action_request %% is already terminal (%%) and cannot be updated',
          OLD.id, OLD.status;
      END IF;
      IF NEW.action <> OLD.action
         OR NEW.arguments IS DISTINCT FROM OLD.arguments
         OR NEW.requesting_agent <> OLD.requesting_agent
         OR NEW.justification <> OLD.justification
         OR NEW.created_at <> OLD.created_at THEN
        RAISE EXCEPTION
          'agent_action_request %% identifying fields are immutable once created (S13 section 3.1)',
          OLD.id;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_SINGLE_TRANSITION_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER agent_action_request_before_update
      BEFORE UPDATE ON agent_action_request
      FOR EACH ROW EXECUTE FUNCTION agent_action_request_single_transition();
    """
)

for _ddl in (_SINGLE_TRANSITION_FUNCTION, _SINGLE_TRANSITION_TRIGGER):
    event.listen(AgentActionRequest.__table__, "after_create", _ddl)

event.listen(
    AgentActionRequest.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS agent_action_request_before_update ON agent_action_request;"
        "DROP FUNCTION IF EXISTS agent_action_request_single_transition();"
    ),
)

# Append-only in spirit (ADR 24): DELETE revoked; the trigger above polices legal UPDATEs.
event.listen(
    AgentActionRequest.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON agent_action_request FROM trueup_app, trueup_worker;"
    ),
)

# No RLS policy (S13 §3.1): access control is @requires_role("adviser", "admin") on every route.


class InvalidAgentActionTransitionError(RuntimeError):
    """Raised when the application layer catches an illegal status transition before the DB
    trigger would."""


class AgentActionRequestRepository(BaseRepository[AgentActionRequest]):
    """No `customer_id_column`: adviser/admin-scoped, not customer-scoped (S13 §3.1)."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=AgentActionRequest)

    def create(
        self,
        *,
        action: AgentActionType,
        arguments: dict[str, Any],
        requesting_agent: str,
        justification: str,
    ) -> uuid.UUID:
        """The only way an `agent_action_request` row is born (ADR 24). Flushes to return the
        new id."""
        row = AgentActionRequest(
            action=action,
            arguments=arguments,
            requesting_agent=requesting_agent,
            justification=justification,
        )
        self.session.add(row)
        self.session.flush()
        return row.id

    def get_by_id(self, request_id: uuid.UUID) -> AgentActionRequest | None:
        return self.session.query(AgentActionRequest).filter_by(id=request_id).first()

    def get_for_update(self, request_id: uuid.UUID) -> AgentActionRequest | None:
        """`SELECT ... FOR UPDATE`: two advisers approving/rejecting concurrently must
        serialize (S13 §6)."""
        statement = (
            select(AgentActionRequest).where(AgentActionRequest.id == request_id).with_for_update()
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_by_status(
        self,
        status: AgentActionStatus,
        *,
        limit: int,
        after: tuple[datetime, uuid.UUID] | None = None,
    ) -> list[AgentActionRequest]:
        """Keyset-paginated on `(created_at, id)`, oldest first (fetches `limit + 1`)."""
        statement = select(AgentActionRequest).where(AgentActionRequest.status == status)
        if after is not None:
            after_created_at, after_id = after
            key = tuple_(AgentActionRequest.created_at, AgentActionRequest.id)
            statement = statement.where(key > (after_created_at, after_id))
        statement = statement.order_by(
            AgentActionRequest.created_at.asc(), AgentActionRequest.id.asc()
        ).limit(limit + 1)
        return list(self.session.execute(statement).scalars().all())

    def approve(
        self,
        row: AgentActionRequest,
        *,
        reviewed_by: uuid.UUID,
        reviewed_at: datetime,
        review_note: str | None,
    ) -> None:
        if row.status is not AgentActionStatus.PENDING:
            raise InvalidAgentActionTransitionError(
                f"agent_action_request {row.id} is {row.status}, not pending; cannot approve"
            )
        row.status = AgentActionStatus.APPROVED
        row.reviewed_by = reviewed_by
        row.reviewed_at = reviewed_at
        row.review_note = review_note

    def reject(
        self,
        row: AgentActionRequest,
        *,
        reviewed_by: uuid.UUID,
        reviewed_at: datetime,
        review_note: str,
    ) -> None:
        if row.status is not AgentActionStatus.PENDING:
            raise InvalidAgentActionTransitionError(
                f"agent_action_request {row.id} is {row.status}, not pending; cannot reject"
            )
        row.status = AgentActionStatus.REJECTED
        row.reviewed_by = reviewed_by
        row.reviewed_at = reviewed_at
        row.review_note = review_note

    def mark_executed(self, row: AgentActionRequest, *, executed_at: datetime) -> None:
        if row.status is not AgentActionStatus.APPROVED:
            raise InvalidAgentActionTransitionError(
                f"agent_action_request {row.id} is {row.status}, not approved; cannot execute"
            )
        row.status = AgentActionStatus.EXECUTED
        row.executed_at = executed_at

    def mark_execution_failed(self, row: AgentActionRequest, *, execution_error: str) -> None:
        if row.status is not AgentActionStatus.APPROVED:
            raise InvalidAgentActionTransitionError(
                f"agent_action_request {row.id} is {row.status}, not approved; cannot fail"
            )
        row.status = AgentActionStatus.EXECUTION_FAILED
        row.execution_error = execution_error


__all__ = [
    "AgentActionRequest",
    "AgentActionRequestRepository",
    "AgentActionStatus",
    "AgentActionType",
    "InvalidAgentActionTransitionError",
]
