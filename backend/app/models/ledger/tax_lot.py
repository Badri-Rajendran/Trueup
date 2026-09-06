"""`tax_lot` (S5 §3.1) — one row per buy fill, never merged even for same-day same-security fills.

Mutable, unlike `journal_entry`/`posting`: it is a *projection* derived from the immutable ledger
(the same shape of problem `order` solves for `order_event`, S3 §3.1) — `quantity_remaining` and
`adjusted_basis` both shrink/grow in place as sells consume the lot and wash-sale adjustments carry
disallowed loss into it (ADR 11). `quantity_remaining >= 0` is enforced by a genuine database
`CHECK` (S5 §3.1's edge case 6, §8's own integration-testing emphasis) since a negative value is a
direct sign of a lot-consumption bug, never a valid state.
"""

from __future__ import annotations

import uuid
from datetime import (
    date,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    datetime,  # noqa: TC003
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, CheckConstraint, Date, DateTime, ForeignKey, String, event, select
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
    """ADR 4: `unspecified` (FIFO applies) vs `specific` (investor override, closes no later than
    `min(expected_settlement_date, confirmation_event)`)."""

    UNSPECIFIED = "unspecified"
    SPECIFIC = "specific"


class TaxLot(Base):
    __tablename__ = "tax_lot"
    __table_args__ = (
        CheckConstraint("quantity_remaining >= 0", name="quantity_remaining_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security.id"), nullable=False
    )
    # One lot per fill, never merged (module docstring) -- the FK target's own uniqueness
    # (`uq_order_event_execution_id`) is what makes this column unique too.
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


# S0 §7.3's role-aware tenant-isolation RLS policy (ADR 17) -- `tax_lot` carries a native
# `customer_id`, same shape as `account`/`order`.
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


class TaxLotRepository(BaseRepository[TaxLot]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=TaxLot, customer_id_column=TaxLot.customer_id)

    def get_by_id(self, lot_id: uuid.UUID) -> TaxLot | None:
        return self.session.query(TaxLot).filter_by(id=lot_id).first()

    def lock_open_fifo(self, customer_id: uuid.UUID, security_id: uuid.UUID) -> list[TaxLot]:
        """Open lots (`quantity_remaining > 0`) for one customer/security, oldest first (ADR 4's
        FIFO default), row-locked for the duration of the consuming transaction -- the per-lot
        analogue of `OrderRepository.get_for_update`, needed because two sell fills for the same
        security could otherwise both read the same lot's `quantity_remaining` before either
        writes it back."""
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
        """Specific-ID override path (ADR 4): row-locks exactly the designated lots. Returns a
        dict rather than a list so the caller can re-apply the investor's own designation order
        and detect a missing/foreign id."""
        if not lot_ids:
            return {}
        statement = select(TaxLot).where(TaxLot.id.in_(lot_ids)).with_for_update()
        lots = self.session.execute(statement).scalars().all()
        return {lot.id: lot for lot in lots}

    def lock_open_for_security(
        self, customer_id: uuid.UUID, security_id: uuid.UUID
    ) -> list[TaxLot]:
        """Every open lot for one customer/security, row-locked -- `CorporateActionService`'s
        split path needs every lot touched atomically, not just a FIFO-ordered subset."""
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
        """Distinct customers with an open position in `security_id` -- how
        `CorporateActionService` finds who a dividend/split applies to, since lot state is the
        only source of truth for holdings (no separate holdings table, S5 §1)."""
        statement = (
            select(TaxLot.customer_id)
            .where(TaxLot.security_id == security_id, TaxLot.quantity_remaining > Units("0"))
            .distinct()
        )
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
        """ADR 11's same-CUSIP repurchase match: the earliest buy within the trailing/forward
        30-day window, excluding the lot the loss sale itself drew down."""
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
