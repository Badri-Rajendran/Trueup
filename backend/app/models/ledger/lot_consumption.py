"""`lot_consumption` (S5 §3.2) — which lot(s) a sell fill drew from; FIFO can span multiple lots.

`sale_date` supports the wash-sale window scan (§5). Mutable like `tax_lot`: `realized_gain_loss`
is amended in place by a wash-sale adjustment (ADR 11).
"""

from __future__ import annotations

import uuid
from datetime import date  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Boolean, Date, ForeignKey, String, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType, Units, UnitsType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.uow import UnitOfWork


class LotConsumption(Base):
    __tablename__ = "lot_consumption"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    closing_fill_execution_id: Mapped[str] = mapped_column(
        String(255), ForeignKey("order_event.execution_id"), nullable=False
    )
    tax_lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_lot.id"), nullable=False
    )
    quantity_consumed: Mapped[Units] = mapped_column(UnitsType, nullable=False)
    realized_gain_loss: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False)
    # Not in S5 §3.2's literal table; added for the §5 wash-sale window scan.
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)


# Mutable in place but must never be deleted (S0 §10.1 F12/I3).
event.listen(
    LotConsumption.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON lot_consumption FROM trueup_app, trueup_worker;"
    ),
)


class LotConsumptionRepository(BaseRepository[LotConsumption]):
    """No `customer_id_column`: per-customer reads join through `tax_lot`."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=LotConsumption)

    def get_by_id(self, consumption_id: uuid.UUID) -> LotConsumption | None:
        return self.session.query(LotConsumption).filter_by(id=consumption_id).first()

    def list_for_closing_fill(self, execution_id: str) -> list[LotConsumption]:
        return list(
            self.session.query(LotConsumption)
            .filter_by(closing_fill_execution_id=execution_id)
            .all()
        )

    def list_realized_in_period(
        self, customer_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> list[LotConsumption]:
        """Every consumption whose `sale_date` falls inside `[period_start, period_end]` (S8 §5)."""
        statement = (
            select(LotConsumption)
            .join(TaxLot, TaxLot.id == LotConsumption.tax_lot_id)
            .where(
                TaxLot.customer_id == customer_id,
                LotConsumption.sale_date >= period_start,
                LotConsumption.sale_date <= period_end,
            )
            .order_by(LotConsumption.sale_date.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def list_by_closing_execution_ids(self, execution_ids: Sequence[str]) -> list[LotConsumption]:
        """Every lot consumption a sell order's own fills drew from (S3 §6 order-detail lot
        linkage), one query."""
        if not execution_ids:
            return []
        statement = select(LotConsumption).where(
            LotConsumption.closing_fill_execution_id.in_(execution_ids)
        )
        return list(self.session.execute(statement).scalars().all())

    def list_for_lots(self, tax_lot_ids: Sequence[uuid.UUID]) -> list[LotConsumption]:
        """Every consumption row against any of the given lots, most-recent sale first
        (GET /api/v1/lots)."""
        if not tax_lot_ids:
            return []
        statement = (
            select(LotConsumption)
            .where(LotConsumption.tax_lot_id.in_(tax_lot_ids))
            .order_by(LotConsumption.sale_date.desc(), LotConsumption.id.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def find_unadjusted_losses_in_window(
        self,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        *,
        window_start: date,
        window_end: date,
    ) -> list[LotConsumption]:
        """ADR 11's reactive side: loss consumptions in the window not already wash-sale-adjusted."""
        already_adjusted = select(WashSaleAdjustment.id).where(
            WashSaleAdjustment.original_lot_consumption_id == LotConsumption.id
        )
        statement = (
            select(LotConsumption)
            .join(TaxLot, TaxLot.id == LotConsumption.tax_lot_id)
            .where(
                TaxLot.customer_id == customer_id,
                TaxLot.security_id == security_id,
                LotConsumption.realized_gain_loss < Money("0.00"),
                LotConsumption.sale_date >= window_start,
                LotConsumption.sale_date <= window_end,
                ~already_adjusted.exists(),
            )
            .with_for_update(of=LotConsumption)
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = ["LotConsumption", "LotConsumptionRepository"]
