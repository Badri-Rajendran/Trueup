"""`reconciliation_break` (S7 §5.2) — one row per detected discrepancy between Trueup's internal
state and one morning's custodian file.

**Append-only for the identifying facts, single controlled transition for resolution** — the same
shape `settlement_obligation` already establishes (S1 §4, ADR 2): `break_type`, `customer_id`,
`expected`, `actual`, `opened_at`, and `import_batch_id` never change once written (S7 §5.2); only
`status`/`resolved_at`/`resolved_by`/`resolution_note` transition, and exactly once, `open ->
resolved`. A `BEFORE UPDATE` trigger enforces both halves at the database, backstopping the
application-layer checks in `ReconciliationBreakRepository.resolve()`.

**FR-44 as a `CHECK` constraint, not only application validation** (S7 §11): `resolved_by` must be
non-null whenever `status = 'resolved'` — there is no system-generated resolution path, by design,
and a `resolved` row with no `resolved_by` is itself a bug, not a valid state the database should
ever accept.
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
    # Nullable only for a break with no single-customer attribution (S7 §5.2: rare, e.g. a
    # malformed file row). No FK: `customer` is a cross-aggregate reference the same way
    # `account.customer_id`/`order.customer_id` predate a formal cross-schema FK convention.
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
    # A human actor id (adviser/admin) -- FR-44: there is no system-generated resolution path.
    # No FK: `staff` predates a formal cross-schema FK convention, matching `customer_id` above.
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(String, nullable=True)
    # Groups this break back to the custodian_file_row rows from the same morning's import (S7
    # §5.2) -- not a formal FK since custodian_file_row has no distinct "batch" entity of its own,
    # only a shared import_batch_id tag on many rows.
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

# DELETE is revoked, matching settlement_obligation's append-only-except-one-transition posture;
# UPDATE stays granted for the one-time open -> resolved transition the trigger above polices.
event.listen(
    ReconciliationBreak.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON reconciliation_break FROM trueup_app, trueup_worker;"
    ),
)

# S0 §7.3's role-aware tenant-isolation RLS policy (ADR 17): a customer session sees only breaks
# attributed to it; a break with no customer attribution (customer_id IS NULL) is visible only to
# adviser/admin, matching a house account's exclusion on `account.customer_id IS NULL`.
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
    """A `resolved` break was passed to `resolve()` again -- status transitions exactly once
    (S7 §5.2)."""


class ReconciliationBreakRepository(BaseRepository[ReconciliationBreak]):
    """No `customer_id_column`: `customer_id` is nullable here (S7 §5.2), and the adviser-facing
    break screen (S7 §8, consumed by S8) is deliberately cross-customer by design, the same shape
    as `AccountRepository`'s adviser/admin branch -- a customer session still gets RLS-level
    scoping from the policy above, this repository does not additionally restrict it."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ReconciliationBreak)

    def get_by_id(self, break_id: uuid.UUID) -> ReconciliationBreak | None:
        return self.session.query(ReconciliationBreak).filter_by(id=break_id).first()

    def list_open(self) -> list[ReconciliationBreak]:
        """Sorted oldest-`opened_at`-first (S7 §7: `age` descending), so the longest-open break is
        always first."""
        return list(
            self.session.query(ReconciliationBreak)
            .filter_by(status=ReconciliationBreakStatus.OPEN)
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
