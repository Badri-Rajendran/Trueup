"""`high_water_mark` (S10 §3.2, ADR 10) — one row per customer, updated in place.

The **one intentional exception** to the append-only posture elsewhere in this design: a
high-water-mark is a derived summary value, not a source-of-truth economic fact. The economic
facts (each day's TWR gain, each charge) remain fully append-only in `fee_accrual`/`fee_charge`;
this row is always re-derivable from them if it were ever lost, so no `append_only` guard applies
here the way it does on `journal_entry`/`posting`.

`peak_value` is stored in dollars but tracks the customer's **TWR-adjusted** value, never the raw
portfolio balance -- see `app.services.fees.high_water_mark_service` for the mechanism that keeps
that true (S10 §8 edge case 2, the "single most consequential correctness requirement" in this
sub-project).
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


class HighWaterMarkRepository(BaseRepository[HighWaterMark]):
    """Not `append_only`: `peak_value`/`updated_at` are ratcheted up in place by design (module
    docstring) -- the one aggregate in this codebase where an `UPDATE` is the intended, correct
    operation rather than a violation `BaseRepository` should reject."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=HighWaterMark, customer_id_column=HighWaterMark.customer_id)

    def get_by_customer(self, customer_id: uuid.UUID) -> HighWaterMark | None:
        statement = self._tenant_scoped(
            select(HighWaterMark).where(HighWaterMark.customer_id == customer_id)
        )
        return self.session.execute(statement).scalar_one_or_none()


__all__ = ["HighWaterMark", "HighWaterMarkRepository"]
