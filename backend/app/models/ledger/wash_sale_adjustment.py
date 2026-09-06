"""`wash_sale_adjustment` (S5 §3.3, ADR 11) — the record of a disallowed loss carried into a
replacement lot's basis.

References `lot_consumption`/`tax_lot` by table name only (`ForeignKey("lot_consumption.id")`),
never by importing those modules -- `lot_consumption.py` imports *this* module (to query "has this
consumption already been adjusted"), so importing back would cycle. `UniqueConstraint` on
`original_lot_consumption_id`: ADR 11's mechanism disallows a given loss sale's loss exactly once
-- a chained wash sale (S5 §7 edge case 2) is a *different* consumption row (the replacement lot's
own later sale), never a second adjustment against the same one.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DDL, ForeignKey, UniqueConstraint, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class WashSaleAdjustment(Base):
    __tablename__ = "wash_sale_adjustment"
    __table_args__ = (
        UniqueConstraint("original_lot_consumption_id", name="uq_wash_sale_original_consumption"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    original_lot_consumption_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lot_consumption.id"), nullable=False
    )
    replacement_tax_lot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tax_lot.id"), nullable=False
    )
    disallowed_amount: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=False
    )


# F12/I3 fix (S0 §10.1 audit): unlike `tax_lot`/`lot_consumption`, this row is never mutated once
# written -- it is itself the immutable correction record ADR 11's mechanism produces, its own
# uniqueness enforcing "exactly once." The S5 migration that created this table carried no REVOKE
# at all, unlike every other money-bearing table in the schema.
event.listen(
    WashSaleAdjustment.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE UPDATE, DELETE ON wash_sale_adjustment FROM trueup_app, trueup_worker;"
    ),
)


class WashSaleAdjustmentRepository(BaseRepository[WashSaleAdjustment]):
    """No `customer_id_column`: no native customer identity (module docstring's schema), matching
    `lot_consumption`'s precedent -- per-customer reads join through `tax_lot`."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=WashSaleAdjustment)

    def get_by_id(self, adjustment_id: uuid.UUID) -> WashSaleAdjustment | None:
        return self.session.query(WashSaleAdjustment).filter_by(id=adjustment_id).first()

    def exists_for_consumption(self, lot_consumption_id: uuid.UUID) -> bool:
        statement = select(
            select(WashSaleAdjustment.id)
            .where(WashSaleAdjustment.original_lot_consumption_id == lot_consumption_id)
            .exists()
        )
        return bool(self.session.execute(statement).scalar_one())


__all__ = ["WashSaleAdjustment", "WashSaleAdjustmentRepository"]
