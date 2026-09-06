"""`customer_model_assignment` (S9 §3.3) — one active model per customer at a time (FR-7);
`customer_id` is the primary key. Reassigning overwrites this row rather than appending history.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from datetime import date  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, ForeignKey, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class CustomerModelAssignment(Base):
    __tablename__ = "customer_model_assignment"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), primary_key=True
    )
    model_portfolio_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("model_portfolio.id"), nullable=False
    )
    assigned_at: Mapped[date] = mapped_column(Date, nullable=False)


# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17).
event.listen(
    CustomerModelAssignment.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE customer_model_assignment ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON customer_model_assignment
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    CustomerModelAssignment.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON customer_model_assignment;"
        "ALTER TABLE customer_model_assignment DISABLE ROW LEVEL SECURITY;"
    ),
)


class CustomerModelAssignmentRepository(BaseRepository[CustomerModelAssignment]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=CustomerModelAssignment,
            customer_id_column=CustomerModelAssignment.customer_id,
        )

    def get_by_customer(self, customer_id: uuid.UUID) -> CustomerModelAssignment | None:
        return (
            self.session.query(CustomerModelAssignment)
            .filter_by(customer_id=customer_id)
            .first()
        )

    def upsert(self, assignment: CustomerModelAssignment) -> CustomerModelAssignment:
        """Assign or reassign: overwrite, not a history table (S9 §3.3)."""
        existing = self.get_by_customer(assignment.customer_id)
        if existing is None:
            self.add(assignment)
            return assignment
        existing.model_portfolio_id = assignment.model_portfolio_id
        existing.assigned_at = assignment.assigned_at
        return existing

    def list_all(self) -> list[CustomerModelAssignment]:
        """Every assigned customer; admin/worker-role only (`MonthlyRebalanceJob`'s driver query, S9 §7)."""
        return self.session.query(CustomerModelAssignment).all()


__all__ = ["CustomerModelAssignment", "CustomerModelAssignmentRepository"]
