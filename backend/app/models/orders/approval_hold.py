"""`approval_hold` (S3 §3.3) — the cash hold behind `awaiting_approval`/not-yet-`submitted` orders
(S3 §4). Exactly one row per order. `release_reason` covers every terminal-non-filled path plus
`approved_and_submitted`; past that, cash is covered by `open_buy_commitments` instead.
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, event, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.orders._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ApprovalHoldStatus(StrEnum):
    ACTIVE = "active"
    RELEASED = "released"


class ApprovalHoldReleaseReason(StrEnum):
    APPROVED_AND_SUBMITTED = "approved_and_submitted"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


class ApprovalHold(Base):
    __tablename__ = "approval_hold"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order.id"), nullable=False, unique=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    amount_money: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    status: Mapped[ApprovalHoldStatus] = mapped_column(
        SQLAlchemyEnum(
            ApprovalHoldStatus, name="approval_hold_status", values_callable=enum_values
        ),
        nullable=False,
        default=ApprovalHoldStatus.ACTIVE,
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[ApprovalHoldReleaseReason | None] = mapped_column(
        SQLAlchemyEnum(
            ApprovalHoldReleaseReason,
            name="approval_hold_release_reason",
            values_callable=enum_values,
        ),
        nullable=True,
    )


# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17).
event.listen(
    ApprovalHold.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE approval_hold ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON approval_hold
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    ApprovalHold.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON approval_hold;"
        "ALTER TABLE approval_hold DISABLE ROW LEVEL SECURITY;"
    ),
)

# Row must never be deleted; it's the record of a cash commitment (S0 §10.1 F12/I3).
event.listen(
    ApprovalHold.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON approval_hold FROM trueup_app, trueup_worker;"
    ),
)


class ApprovalHoldRepository(BaseRepository[ApprovalHold]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ApprovalHold, customer_id_column=ApprovalHold.customer_id)

    def get_by_order_id(self, order_id: uuid.UUID) -> ApprovalHold | None:
        return self.session.query(ApprovalHold).filter_by(order_id=order_id).first()

    def active_total_for_customer(self, customer_id: uuid.UUID) -> Money:
        """`CashPolicyService.HoldsProvider.holds` (S1 §5): sum of every `active` hold."""
        statement = self._tenant_scoped(select(ApprovalHold)).where(
            ApprovalHold.customer_id == customer_id,
            ApprovalHold.status == ApprovalHoldStatus.ACTIVE,
        )
        total = Money("0.00")
        for hold in self.session.execute(statement).scalars():
            total += hold.amount_money
        return total


__all__ = [
    "ApprovalHold",
    "ApprovalHoldReleaseReason",
    "ApprovalHoldRepository",
    "ApprovalHoldStatus",
]
