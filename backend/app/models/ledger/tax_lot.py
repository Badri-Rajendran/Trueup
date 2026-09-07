"""`tax_lot` (S5 §3.1) — one row per buy fill, never merged even for same-day same-security fills.

Mutable projection: `quantity_remaining`/`adjusted_basis` shrink/grow in place as sells consume the
lot and wash-sale adjustments carry disallowed loss into it (ADR 11). `quantity_remaining >= 0` is a DB `CHECK`.
"""

from __future__ import annotations

import uuid
from datetime import (
    date,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    datetime,  # noqa: TC003
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    DDL,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    event,
    select,
)
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType, Units, UnitsType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.uow import UnitOfWork


class LotDesignation(StrEnum):
    """ADR 4: `unspecified` (FIFO) vs `specific` (investor override)."""

    UNSPECIFIED = "unspecified"
    SPECIFIC = "specific"


class TaxLot(Base):
    __tablename__ = "tax_lot"
    __table_args__ = (
        CheckConstraint("quantity_remaining >= 0", name="quantity_remaining_non_negative"),
        # S12 §3: S5 §4's FIFO ordering selects lots by this exact filter+order.
        Index("ix_tax_lot_customer_security_acquired", "customer_id", "security_id", "acquired_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security.id"), nullable=False
    )
    # One lot per fill, never merged (module docstring).
    opening_fill_execution_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("order_event.execution_id"), nullable=False, unique=True
    )
    quantity_opened: Mapped[Units] = mapped_column(UnitsType, nullable=False)
    quantity_remaining: Mapped[Units] = mapped_column(UnitsType, nullable=False)
    original_cost_basis: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    # Starts equal to original_cost_basis; carries wash-sale-disallowed loss (ADR 11, S1 §9).
    adjusted_basis: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    acquired_at: Mapped[date] = mapped_column(Date, nullable=False)
    designation: Mapped[LotDesignation] = mapped_column(
        SQLAlchemyEnum(LotDesignation, name="lot_designation", values_callable=enum_values),
        nullable=False,
        default=LotDesignation.UNSPECIFIED,
    )
    designation_window_closes_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17).
event.listen(
    TaxLot.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE tax_lot ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tax_lot
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    TaxLot.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON tax_lot;"
        "ALTER TABLE tax_lot DISABLE ROW LEVEL SECURITY;"
    ),
)

# Mutable projection, but must never be deleted (S0 §10.1 F12/I3).
event.listen(
    TaxLot.__table__,
    "after_create",
    DDL("REVOKE DELETE ON tax_lot FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class TaxLotRepository(BaseRepository[TaxLot]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=TaxLot, customer_id_column=TaxLot.customer_id)

    def get_by_id(self, lot_id: uuid.UUID) -> TaxLot | None:
        return self.session.query(TaxLot).filter_by(id=lot_id).first()

    def lock_open_fifo(self, customer_id: uuid.UUID, security_id: uuid.UUID) -> list[TaxLot]:
        """Open lots for one customer/security, oldest first, row-locked (ADR 4 FIFO default)."""
        statement = (
            select(TaxLot)
            .where(
                TaxLot.customer_id == customer_id,
                TaxLot.security_id == security_id,
                TaxLot.quantity_remaining > Units("0"),
            )
            .order_by(TaxLot.acquired_at.asc(), TaxLot.id.asc())
            .with_for_update()
        )
        return list(self.session.execute(statement).scalars().all())

    def lock_by_ids(self, lot_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, TaxLot]:
        """Specific-ID override path (ADR 4): row-locks exactly the designated lots."""
        if not lot_ids:
            return {}
        statement = select(TaxLot).where(TaxLot.id.in_(lot_ids)).with_for_update()
        lots = self.session.execute(statement).scalars().all()
        return {lot.id: lot for lot in lots}

    def lock_open_for_security(
        self, customer_id: uuid.UUID, security_id: uuid.UUID
    ) -> list[TaxLot]:
        """Every open lot for one customer/security, row-locked (`CorporateActionService` split path)."""
        statement = (
            select(TaxLot)
            .where(
                TaxLot.customer_id == customer_id,
                TaxLot.security_id == security_id,
                TaxLot.quantity_remaining > Units("0"),
            )
            .with_for_update()
        )
        return list(self.session.execute(statement).scalars().all())

    def list_customers_holding(self, security_id: uuid.UUID) -> list[uuid.UUID]:
        """Distinct customers with an open position in `security_id` (dividend/split fan-out)."""
        statement = (
            select(TaxLot.customer_id)
            .where(TaxLot.security_id == security_id, TaxLot.quantity_remaining > Units("0"))
            .distinct()
        )
        return list(self.session.execute(statement).scalars().all())

    def list_by_opening_execution_ids(self, execution_ids: Sequence[str]) -> list[TaxLot]:
        """Every lot a buy order's own fills opened (S3 §6 order-detail lot linkage), one query."""
        if not execution_ids:
            return []
        statement = select(TaxLot).where(TaxLot.opening_fill_execution_id.in_(execution_ids))
        return list(self.session.execute(statement).scalars().all())

    def list_for_customer(self, customer_id: uuid.UUID) -> list[TaxLot]:
        """Every lot ever opened for this customer, oldest-acquired first (`GET /api/v1/lots`, S8 §3)."""
        statement = (
            select(TaxLot)
            .where(TaxLot.customer_id == customer_id)
            .order_by(TaxLot.acquired_at.asc(), TaxLot.id.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_by_ids(self, lot_ids: Sequence[uuid.UUID]) -> list[TaxLot]:
        """Plain, non-locking bulk fetch, for a read-only consumer (statement export, S8 §5)."""
        if not lot_ids:
            return []
        statement = select(TaxLot).where(TaxLot.id.in_(lot_ids))
        return list(self.session.execute(statement).scalars().all())

    def total_remaining(self, customer_id: uuid.UUID, security_id: uuid.UUID) -> Units:
        lots = self.lock_open_for_security(customer_id, security_id)
        total = Units("0")
        for lot in lots:
            total += lot.quantity_remaining
        return total

    def find_earliest_replacement_in_window(
        self,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        *,
        window_start: date,
        window_end: date,
        exclude_lot_id: uuid.UUID,
    ) -> TaxLot | None:
        """ADR 11's same-CUSIP repurchase match: earliest buy in the window, excluding the sold lot."""
        statement = (
            select(TaxLot)
            .where(
                TaxLot.customer_id == customer_id,
                TaxLot.security_id == security_id,
                TaxLot.id != exclude_lot_id,
                TaxLot.acquired_at >= window_start,
                TaxLot.acquired_at <= window_end,
            )
            .order_by(TaxLot.acquired_at.asc(), TaxLot.id.asc())
            .with_for_update()
        )
        return self.session.execute(statement).scalars().first()


__all__ = ["LotDesignation", "TaxLot", "TaxLotRepository"]
