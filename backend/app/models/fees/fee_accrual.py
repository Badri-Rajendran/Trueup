"""`fee_accrual` (S10 §3.3, ADR 10) — one row per customer per day, append-only.

`UNIQUE (customer_id, accrual_date)` is `DailyFeeAccrualJob`'s idempotency key (S10 §8 edge case 4).
"""

from __future__ import annotations

import uuid
from datetime import date  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, ForeignKey, UniqueConstraint, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class FeeAccrual(Base):
    __tablename__ = "fee_accrual"
    __table_args__ = (
        UniqueConstraint("customer_id", "accrual_date", name="uq_fee_accrual_customer_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    accrual_date: Mapped[date] = mapped_column(Date, nullable=False)
    # TWR-derived dollar gain above the high-water-mark; zero below peak (S10 §3.3).
    gain_amount: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    fee_amount: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=False
    )


event.listen(
    FeeAccrual.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE fee_accrual ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_accrual
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    FeeAccrual.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON fee_accrual;"
        "ALTER TABLE fee_accrual DISABLE ROW LEVEL SECURITY;"
    ),
)
event.listen(
    FeeAccrual.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON fee_accrual FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class FeeAccrualRepository(BaseRepository[FeeAccrual]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=FeeAccrual, customer_id_column=FeeAccrual.customer_id)

    def add_for_date(self, accrual: FeeAccrual) -> None:
        self.add(accrual)

    def list_for_period(
        self, customer_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> list[FeeAccrual]:
        """Every accrual row within a billing period, inclusive of both boundaries (S10 §5)."""
        statement = self._tenant_scoped(
            select(FeeAccrual).where(
                FeeAccrual.customer_id == customer_id,
                FeeAccrual.accrual_date >= period_start,
                FeeAccrual.accrual_date <= period_end,
            )
        )
        return list(self.session.execute(statement).scalars().all())

    def list_customers_with_accruals_in_period(
        self, *, period_start: date, period_end: date
    ) -> list[uuid.UUID]:
        """`MonthlyFeeChargeJob`'s driver query (S10 §5); admin/worker-role, cross-customer."""
        statement = (
            select(FeeAccrual.customer_id)
            .where(
                FeeAccrual.accrual_date >= period_start,
                FeeAccrual.accrual_date <= period_end,
            )
            .distinct()
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = ["FeeAccrual", "FeeAccrualRepository"]
