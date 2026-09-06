"""`sub_period_return` (S4 §3.5, ADR 3) — one stored row per TWR sub-period.

Bitemporal and append-only: a restated sub-period is a new row, never an `UPDATE`. `TwrService`
reads the latest `recorded_at` per `(customer_id, sub_period_start, sub_period_end)`.
"""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    date,
    datetime,
)
from decimal import Decimal  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, UniqueConstraint, func, select
from sqlalchemy import Date as SQLAlchemyDate
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork
    from app.core.watermark import Watermark


class SubPeriodReturn(Base):
    __tablename__ = "sub_period_return"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "sub_period_start",
            "sub_period_end",
            "recorded_at",
            name="uq_sub_period_return_customer_period_recorded",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    sub_period_start: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    sub_period_end: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    # Wider than Money's 4dp (S4 §3.5); a ratio, not a money/units/price dimension (ADR 16).
    return_pct: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    value_begin: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    value_end: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    flow_amount: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    is_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SubPeriodReturnRepository(BaseRepository[SubPeriodReturn]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=SubPeriodReturn,
            customer_id_column=SubPeriodReturn.customer_id,
            recorded_at_column=SubPeriodReturn.recorded_at,
        )

    def latest_for_sub_period(
        self, *, customer_id: uuid.UUID, sub_period_start: date, sub_period_end: date
    ) -> SubPeriodReturn | None:
        """The newest-`recorded_at` stored row for this sub-period, if one exists (S4 §5)."""
        return (
            self.session.query(SubPeriodReturn)
            .filter_by(
                customer_id=customer_id,
                sub_period_start=sub_period_start,
                sub_period_end=sub_period_end,
            )
            .order_by(SubPeriodReturn.recorded_at.desc())
            .first()
        )

    def as_of_for_sub_period(
        self,
        *,
        customer_id: uuid.UUID,
        sub_period_start: date,
        sub_period_end: date,
        as_of: Watermark,
    ) -> SubPeriodReturn | None:
        """The newest-`recorded_at` row for this sub-period visible as of a past watermark (S6 §6/§7)."""
        return (
            self.session.query(SubPeriodReturn)
            .filter(
                SubPeriodReturn.customer_id == customer_id,
                SubPeriodReturn.sub_period_start == sub_period_start,
                SubPeriodReturn.sub_period_end == sub_period_end,
                SubPeriodReturn.recorded_at <= as_of.cutoff,
            )
            .order_by(SubPeriodReturn.recorded_at.desc())
            .first()
        )

    def containing(self, *, customer_id: uuid.UUID, on_date: date) -> list[SubPeriodReturn]:
        """The latest-`recorded_at` row for every distinct stored window containing `on_date` (S6 §5)."""
        statement = (
            select(SubPeriodReturn)
            .where(
                SubPeriodReturn.customer_id == customer_id,
                SubPeriodReturn.sub_period_start <= on_date,
                SubPeriodReturn.sub_period_end >= on_date,
            )
            .order_by(
                SubPeriodReturn.sub_period_start,
                SubPeriodReturn.sub_period_end,
                SubPeriodReturn.recorded_at.desc(),
            )
        )
        rows = self.session.execute(statement).scalars().all()
        latest_by_window: dict[tuple[date, date], SubPeriodReturn] = {}
        for row in rows:
            latest_by_window.setdefault((row.sub_period_start, row.sub_period_end), row)
        return list(latest_by_window.values())
