"""`lot_consumption` (S5 §3.2) — which lot(s) a sell fill drew from; a sell can span multiple lots
(FIFO exhausts the oldest before moving to the next).

**`sale_date` is a deliberate, documented addition beyond §3.2's literal column list.** §5's own
wash-sale algorithm keys its reactive window off `lot_consumption.sale_date - 30 days` /
`+ 30 days`, but nothing else in this row (or in `order_event`, which has no effective-date concept
of its own) carries that date -- without storing it here, the reactive "does a past loss sale fall
in this new buy's window" scan (`WashSaleService.on_buy_fill`) has no way to query it. Filled in
from the same NY-anchored fill date the closing `trade_sell` journal entry's `effective_date` uses.

Mutable like `tax_lot` (see that module's docstring): `realized_gain_loss` is amended in place when
a wash-sale adjustment disallows part of the loss (ADR 11 -- "the sale's own recognized loss
shrinks"), never re-posted as a new row.
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
    # See module docstring -- not in S5 §3.2's literal table, added to make its own §5 algorithm
    # implementable.
    sale_date: Mapped[date] = mapped_column(Date, nullable=False)


# F12/I3 fix (S0 §10.1 audit): mutable in place (module docstring: `realized_gain_loss` is amended
# by a wash-sale adjustment, ADR 11), but must never be deleted; the S5 migration that created
# this table carried no REVOKE at all, unlike every other money-bearing table in the schema.
event.listen(
    LotConsumption.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON lot_consumption FROM trueup_app, trueup_worker;"
    ),
)


class LotConsumptionRepository(BaseRepository[LotConsumption]):
    """No `customer_id_column`: `lot_consumption` carries no customer identity of its own (module
    docstring's schema), matching `journal_entry`/`order_event`'s precedent -- per-customer reads
    join through `tax_lot`, which does carry `customer_id`."""

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

    def find_unadjusted_losses_in_window(
        self,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        *,
        window_start: date,
        window_end: date,
    ) -> list[LotConsumption]:
        """ADR 11's reactive side: loss consumptions of `security_id`, sold inside the window a
        *new* buy fill just opened, that have not already been carried into a wash-sale
        adjustment (`NOT EXISTS` rather than a join, so a consumption already adjusted -- one
        `wash_sale_adjustment` per `original_lot_consumption_id`, S5 §3.3 -- is never revisited)."""
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
