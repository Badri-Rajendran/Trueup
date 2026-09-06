"""`fee_restatement_disclosure` (S10 §6, ADR 10) — flags a customer account when a restatement
lands for a period that already has a `succeeded` `fee_charge`.

Append-only: once a disclosure is recorded, it is a durable audit fact of "we told the customer
this happened," never edited or removed. `customer_id` is denormalized (see `dunning_state`'s
identical precedent) so a customer's own session can read their disclosures via RLS without joining
through `fee_charge`.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, event, func, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class FeeRestatementDisclosure(Base):
    __tablename__ = "fee_restatement_disclosure"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    fee_charge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fee_charge.id"), nullable=False
    )
    restatement_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("restatement_event.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


event.listen(
    FeeRestatementDisclosure.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE fee_restatement_disclosure ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_restatement_disclosure
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    FeeRestatementDisclosure.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON fee_restatement_disclosure;"
        "ALTER TABLE fee_restatement_disclosure DISABLE ROW LEVEL SECURITY;"
    ),
)
event.listen(
    FeeRestatementDisclosure.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE UPDATE, DELETE ON fee_restatement_disclosure FROM trueup_app, trueup_worker;"
    ),
)


class FeeRestatementDisclosureRepository(BaseRepository[FeeRestatementDisclosure]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=FeeRestatementDisclosure,
            customer_id_column=FeeRestatementDisclosure.customer_id,
        )

    def list_for_customer(self, customer_id: uuid.UUID) -> list[FeeRestatementDisclosure]:
        statement = self._tenant_scoped(
            select(FeeRestatementDisclosure).where(
                FeeRestatementDisclosure.customer_id == customer_id
            )
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = ["FeeRestatementDisclosure", "FeeRestatementDisclosureRepository"]
