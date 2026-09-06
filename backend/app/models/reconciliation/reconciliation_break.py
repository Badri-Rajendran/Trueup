"""`reconciliation_break` (S7 §5.2) — one row per detected discrepancy between Trueup's internal
state and one morning's custodian file.

Append-only for the identifying facts; `status`/`resolved_*` transition exactly once, `open ->
resolved`, via a `BEFORE UPDATE` trigger (same shape as `settlement_obligation`, S1 §4, ADR 2).
FR-44: `resolved_by` non-null whenever `status = 'resolved'` is a `CHECK` constraint (S7 §11).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, CheckConstraint, DateTime, Index, String, event
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class ReconciliationBreakType(StrEnum):
    POSITION_MISMATCH = "position_mismatch"
    CASH_MISMATCH = "cash_mismatch"
    UNMATCHED_CUSTODIAN_TRANSACTION = "unmatched_custodian_transaction"
    UNMATCHED_INTERNAL_TRANSACTION = "unmatched_internal_transaction"


class ReconciliationBreakStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"


class ReconciliationBreak(Base):
    __tablename__ = "reconciliation_break"
    __table_args__ = (
        CheckConstraint(
            "(status <> 'resolved') OR (resolved_by IS NOT NULL)",
            name="resolved_break_requires_resolver",
        ),
        # S12 §3: S7 §7's aged-break-list query filters on status, ordered by opened_at.
        Index("ix_reconciliation_break_status_opened", "status", "opened_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    break_type: Mapped[ReconciliationBreakType] = mapped_column(
        SQLAlchemyEnum(
            ReconciliationBreakType, name="reconciliation_break_type", values_callable=_enum_values
        ),
        nullable=False,
    )
    # Nullable only for a break with no single-customer attribution (S7 §5.2). No FK: predates a
    # formal cross-schema FK convention.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expected: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    actual: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[ReconciliationBreakStatus] = mapped_column(
        SQLAlchemyEnum(
            ReconciliationBreakStatus,
            name="reconciliation_break_status",
            values_callable=_enum_values,
        ),
        nullable=False,
        default=ReconciliationBreakStatus.OPEN,
        server_default=ReconciliationBreakStatus.OPEN.value,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # A human actor id (adviser/admin) -- FR-44: no system-generated resolution path. No FK.
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Groups this break back to the custodian_file_row rows from the same morning's import
    # (S7 §5.2).
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


_SINGLE_TRANSITION_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION reconciliation_break_single_transition() RETURNS trigger AS $$
    BEGIN
      IF OLD.status <> 'open' THEN
        RAISE EXCEPTION 'reconciliation_break %% is already terminal (%%) and cannot be updated',
          OLD.id, OLD.status;
      END IF;
      IF NEW.break_type <> OLD.break_type
         OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
         OR NEW.expected IS DISTINCT FROM OLD.expected
         OR NEW.actual IS DISTINCT FROM OLD.actual
         OR NEW.opened_at <> OLD.opened_at
         OR NEW.import_batch_id <> OLD.import_batch_id THEN
        RAISE EXCEPTION
          'reconciliation_break %% identifying fields are immutable once created (S7 section 5.2)',
          OLD.id;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_SINGLE_TRANSITION_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER reconciliation_break_before_update
      BEFORE UPDATE ON reconciliation_break
      FOR EACH ROW EXECUTE FUNCTION reconciliation_break_single_transition();
    """
)

for _ddl in (_SINGLE_TRANSITION_FUNCTION, _SINGLE_TRANSITION_TRIGGER):
    event.listen(ReconciliationBreak.__table__, "after_create", _ddl)

event.listen(
    ReconciliationBreak.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS reconciliation_break_before_update ON reconciliation_break;"
        "DROP FUNCTION IF EXISTS reconciliation_break_single_transition();"
    ),
)

# DELETE revoked; UPDATE stays granted for the one-time open -> resolved transition above.
event.listen(
    ReconciliationBreak.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON reconciliation_break FROM trueup_app, trueup_worker;"
    ),
)

# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17); a break with no customer attribution
# is visible only to adviser/admin.
event.listen(
    ReconciliationBreak.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE reconciliation_break ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON reconciliation_break
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    ReconciliationBreak.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON reconciliation_break;"
        "ALTER TABLE reconciliation_break DISABLE ROW LEVEL SECURITY;"
    ),
)


class AlreadyResolvedError(RuntimeError):
    """A `resolved` break was passed to `resolve()` again; status transitions exactly once
    (S7 §5.2)."""


class ReconciliationBreakRepository(BaseRepository[ReconciliationBreak]):
    """No `customer_id_column`: `customer_id` is nullable (S7 §5.2); the break screen is
    deliberately cross-customer by design (S7 §8)."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ReconciliationBreak)

    def get_by_id(self, break_id: uuid.UUID) -> ReconciliationBreak | None:
        return self.session.query(ReconciliationBreak).filter_by(id=break_id).first()

    def list_open(self) -> list[ReconciliationBreak]:
        """Sorted oldest-`opened_at`-first (S7 §7): the longest-open break is always first."""
        return list(
            self.session.query(ReconciliationBreak)
            .filter_by(status=ReconciliationBreakStatus.OPEN)
            .order_by(ReconciliationBreak.opened_at.asc())
            .all()
        )

    def list_open_for_customer(self, customer_id: uuid.UUID) -> list[ReconciliationBreak]:
        """`GET /admin/customers/<id>` surfaces a customer's own open break, oldest first
        (S8 §6)."""
        return list(
            self.session.query(ReconciliationBreak)
            .filter_by(status=ReconciliationBreakStatus.OPEN, customer_id=customer_id)
            .order_by(ReconciliationBreak.opened_at.asc())
            .all()
        )

    def resolve(
        self,
        break_row: ReconciliationBreak,
        *,
        resolved_by: uuid.UUID,
        resolved_at: datetime,
        resolution_note: str,
    ) -> None:
        if break_row.status is not ReconciliationBreakStatus.OPEN:
            raise AlreadyResolvedError(
                f"reconciliation_break {break_row.id} is already {break_row.status}; status "
                "transitions exactly once (S7 §5.2)"
            )
        break_row.status = ReconciliationBreakStatus.RESOLVED
        break_row.resolved_at = resolved_at
        break_row.resolved_by = resolved_by
        break_row.resolution_note = resolution_note


__all__ = [
    "AlreadyResolvedError",
    "ReconciliationBreak",
    "ReconciliationBreakRepository",
    "ReconciliationBreakStatus",
    "ReconciliationBreakType",
]
