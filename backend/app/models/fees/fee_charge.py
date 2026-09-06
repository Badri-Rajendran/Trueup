"""`fee_charge` (S10 §3.4, ADR 10) — one row per customer per billing period.

Unlike `fee_accrual`, this row is legitimately updated in place as the charge's lifecycle
progresses (`pending -> succeeded|failed|dunning`, `stripe_charge_id`/`journal_entry_id` set on
success) -- so its repository is **not** `append_only`. The one column that must never change once
set is `as_published_watermark` (FR-47: the fee basis locks to the as-published figure at charge
time, and a later restatement must never reopen it) -- enforced by a DB-level trigger, per the
spec's own required test ("attempt an UPDATE, assert it's rejected at the DB level"), not only by
application discipline.
"""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003
    date,
    datetime,
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, Date, DateTime, ForeignKey, String, event, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.fees._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class FeeChargeStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DUNNING = "dunning"


class FeeCharge(Base):
    __tablename__ = "fee_charge"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    billing_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    billing_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    total_accrued: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    # Set once at charge time (S10 §5), never updated after — see module docstring's trigger.
    as_published_watermark: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[FeeChargeStatus] = mapped_column(
        SQLAlchemyEnum(FeeChargeStatus, name="fee_charge_status", values_callable=enum_values),
        nullable=False,
        default=FeeChargeStatus.PENDING,
        server_default=FeeChargeStatus.PENDING.value,
    )
    # The dedupe key for Stripe Billing webhook events (S10 §3.4, ADR 7's pattern).
    stripe_charge_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    journal_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=True
    )


_WATERMARK_IMMUTABLE_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION fee_charge_watermark_immutable() RETURNS trigger AS $$
    BEGIN
      IF OLD.as_published_watermark IS NOT NULL
         AND NEW.as_published_watermark IS DISTINCT FROM OLD.as_published_watermark THEN
        RAISE EXCEPTION
          'fee_charge.as_published_watermark is immutable once set (FR-47), row %%',
          OLD.id;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_WATERMARK_IMMUTABLE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER fee_charge_watermark_immutable
      BEFORE UPDATE ON fee_charge
      FOR EACH ROW EXECUTE FUNCTION fee_charge_watermark_immutable();
    """
)

for _ddl in (_WATERMARK_IMMUTABLE_FUNCTION, _WATERMARK_IMMUTABLE_TRIGGER):
    event.listen(FeeCharge.__table__, "after_create", _ddl)

event.listen(
    FeeCharge.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS fee_charge_watermark_immutable ON fee_charge;"
        "DROP FUNCTION IF EXISTS fee_charge_watermark_immutable();"
    ),
)

event.listen(
    FeeCharge.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE fee_charge ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_charge
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    FeeCharge.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON fee_charge;"
        "ALTER TABLE fee_charge DISABLE ROW LEVEL SECURITY;"
    ),
)


class FeeChargeRepository(BaseRepository[FeeCharge]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=FeeCharge, customer_id_column=FeeCharge.customer_id)

    def get_by_id(self, charge_id: uuid.UUID) -> FeeCharge | None:
        statement = self._tenant_scoped(select(FeeCharge).where(FeeCharge.id == charge_id))
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_stripe_charge_id(self, stripe_charge_id: str) -> FeeCharge | None:
        """Admin/worker-role only (the webhook handler runs as `SessionRole.ADMIN`, matching
        `KycService.apply_verification_verdict`'s own precedent)."""
        return (
            self.session.query(FeeCharge)
            .filter_by(stripe_charge_id=stripe_charge_id)
            .one_or_none()
        )

    def get_for_period(
        self, customer_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> FeeCharge | None:
        statement = self._tenant_scoped(
            select(FeeCharge).where(
                FeeCharge.customer_id == customer_id,
                FeeCharge.billing_period_start == period_start,
                FeeCharge.billing_period_end == period_end,
            )
        )
        return self.session.execute(statement).scalar_one_or_none()

    def list_for_customer(self, customer_id: uuid.UUID) -> list[FeeCharge]:
        statement = self._tenant_scoped(
            select(FeeCharge).where(FeeCharge.customer_id == customer_id)
        ).order_by(FeeCharge.billing_period_start.desc())
        return list(self.session.execute(statement).scalars().all())

    def has_succeeded_charge_for_period(
        self, customer_id: uuid.UUID, *, period_start: date, period_end: date
    ) -> FeeCharge | None:
        """S10 §6: `RestatementService`'s hook -- does an already-`succeeded` charge exist for the
        period a restatement just touched? Admin/worker-role query (`RestatementService` runs
        under whatever role posted the correcting entry, not necessarily the affected customer's
        own session)."""
        statement = select(FeeCharge).where(
            FeeCharge.customer_id == customer_id,
            FeeCharge.billing_period_start <= period_end,
            FeeCharge.billing_period_end >= period_start,
            FeeCharge.status == FeeChargeStatus.SUCCEEDED,
        )
        return self.session.execute(statement).scalar_one_or_none()


__all__ = ["FeeCharge", "FeeChargeRepository", "FeeChargeStatus"]
