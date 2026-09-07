"""`wash_sale_adjustment` (S5 §3.3, ADR 11) — record of a disallowed loss carried into a
replacement lot's basis. References `lot_consumption`/`tax_lot` by table name only to avoid an
import cycle. `UniqueConstraint` on `original_lot_consumption_id` disallows a loss exactly once.
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
    from collections.abc import Sequence

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


# Immutable correction record; never mutated once written (S0 §10.1 F12/I3).
event.listen(
    WashSaleAdjustment.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE UPDATE, DELETE ON wash_sale_adjustment FROM trueup_app, trueup_worker;"
    ),
)


class WashSaleAdjustmentRepository(BaseRepository[WashSaleAdjustment]):
    """No `customer_id_column`: per-customer reads join through `tax_lot`."""

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

    def list_for_replacement_lots(
        self, replacement_tax_lot_ids: Sequence[uuid.UUID]
    ) -> list[WashSaleAdjustment]:
        """Every disallowance folded into any of these lots' basis, in one query (GET /api/v1/lots).
        A lot can receive more than one disallowance over its life; callers sum, never assume ≤1."""
        if not replacement_tax_lot_ids:
            return []
        statement = select(WashSaleAdjustment).where(
            WashSaleAdjustment.replacement_tax_lot_id.in_(replacement_tax_lot_ids)
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = ["WashSaleAdjustment", "WashSaleAdjustmentRepository"]
