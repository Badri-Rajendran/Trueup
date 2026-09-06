"""`payment_method` (S10 §7, ADR 10) — the customer's Stripe-linked payment method for fee billing.

**Not in S10 §3's literal schema list** -- that section defines the fee-lifecycle tables but never
says where "the customer's Stripe-linked payment method" (§4/§5/§7's own phrase) is actually
recorded. `POST /api/v1/payment-methods` and `MonthlyFeeChargeJob`/`DunningService` both need a
concrete place to read/write it, so this table closes that gap the same way `security`/
`market_calendar_cache`/`sub_period_return`/`customer_cash_lock` were each added to the spec that
owns their domain before any code (`DECISION-LOG.md`, 2026-09-04 "Spec gaps closed"). One row per
customer (Stripe Elements attaches one default payment method per customer in this design; no
multi-card wallet in v1). Flagged in the fee-engineer close-out report, not edited into
`docs/specs/10-performance-fees.md` directly -- that file is not this agent's to edit.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, String, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class PaymentMethod(Base):
    __tablename__ = "payment_method"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), primary_key=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    stripe_payment_method_id: Mapped[str] = mapped_column(String(255), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


event.listen(
    PaymentMethod.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE payment_method ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON payment_method
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    PaymentMethod.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON payment_method;"
        "ALTER TABLE payment_method DISABLE ROW LEVEL SECURITY;"
    ),
)


class PaymentMethodRepository(BaseRepository[PaymentMethod]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=PaymentMethod, customer_id_column=PaymentMethod.customer_id)

    def get_by_customer(self, customer_id: uuid.UUID) -> PaymentMethod | None:
        statement = self._tenant_scoped(
            select(PaymentMethod).where(PaymentMethod.customer_id == customer_id)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def upsert(self, method: PaymentMethod) -> PaymentMethod:
        existing = self.get_by_customer(method.customer_id)
        if existing is None:
            self.add(method)
            return method
        existing.stripe_customer_id = method.stripe_customer_id
        existing.stripe_payment_method_id = method.stripe_payment_method_id
        existing.updated_at = method.updated_at
        return existing


__all__ = ["PaymentMethod", "PaymentMethodRepository"]
