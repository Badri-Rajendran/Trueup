"""`customer_cash_lock` (S1 §3.5) — a deliberately payload-free row that exists only to be locked.

Every cash-consuming operation (order hold in S3, withdrawal in S2, fee charge in S10) must
acquire `SELECT ... FOR UPDATE` on this row inside the same `UnitOfWork` transaction that
evaluates a cash-policy check and writes its effect, serializing concurrent cash decisions for one
customer without blocking unrelated writes to `customer` itself (§3.5). `acquire()` is the single
supported way to take the lock, so no caller hand-writes the `FOR UPDATE` query.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from typing import TYPE_CHECKING

from sqlalchemy import DDL, ForeignKey, event, select
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class CustomerCashLock(Base):
    __tablename__ = "customer_cash_lock"

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), primary_key=True
    )


event.listen(
    CustomerCashLock.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE customer_cash_lock ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON customer_cash_lock
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    CustomerCashLock.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON customer_cash_lock;"
        "ALTER TABLE customer_cash_lock DISABLE ROW LEVEL SECURITY;"
    ),
)


class CustomerCashLockMissingError(RuntimeError):
    """Raised when `acquire()` finds no lock row for the customer -- every customer must have one,
    created alongside the customer row (§3.5); a missing row means that invariant was violated
    somewhere upstream, not a normal "no lock needed" case."""


class CustomerCashLockRepository(BaseRepository[CustomerCashLock]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow, entity=CustomerCashLock, customer_id_column=CustomerCashLock.customer_id
        )

    def create_for_customer(self, customer_id: uuid.UUID) -> CustomerCashLock:
        row = CustomerCashLock(customer_id=customer_id)
        self.add(row)
        return row

    def acquire(self, customer_id: uuid.UUID) -> None:
        """Blocks until `SELECT ... FOR UPDATE` on this customer's lock row is granted. A
        precondition for using `withdrawable`/`investable` to make a *write* decision (§3.5) --
        not required for a read-only display of those figures."""
        statement = (
            select(CustomerCashLock)
            .where(CustomerCashLock.customer_id == customer_id)
            .with_for_update()
        )
        row = self.session.execute(statement).scalar_one_or_none()
        if row is None:
            raise CustomerCashLockMissingError(
                f"no customer_cash_lock row for customer {customer_id}"
            )
