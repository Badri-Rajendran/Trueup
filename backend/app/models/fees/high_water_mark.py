"""`high_water_mark` (S10 §3.2, ADR 10) — one row per customer, updated in place.

The one intentional exception to append-only: derived from `fee_accrual`/`fee_charge`, re-derivable
if lost. `peak_value` tracks TWR-adjusted value, not raw balance (S10 §8 edge case 2).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class HighWaterMark(Base):
    __tablename__ = "high_water_mark"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), primary_key=True
    )
    peak_value: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


event.listen(
    HighWaterMark.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE high_water_mark ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON high_water_mark
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    HighWaterMark.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON high_water_mark;"
        "ALTER TABLE high_water_mark DISABLE ROW LEVEL SECURITY;"
    ),
)

# Row must never be deleted; losing it resets the customer's high-water-mark to zero (S0 §10.1 F12).
event.listen(
    HighWaterMark.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE DELETE ON high_water_mark FROM trueup_app, trueup_worker;"
    ),
)


class HighWaterMarkRepository(BaseRepository[HighWaterMark]):
    """Not `append_only`: `peak_value`/`updated_at` are ratcheted up in place by design."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=HighWaterMark, customer_id_column=HighWaterMark.customer_id)

    def get_by_customer(self, customer_id: uuid.UUID) -> HighWaterMark | None:
        statement = self._tenant_scoped(
            select(HighWaterMark).where(HighWaterMark.customer_id == customer_id)
        )
        return self.session.execute(statement).scalar_one_or_none()


__all__ = ["HighWaterMark", "HighWaterMarkRepository"]
