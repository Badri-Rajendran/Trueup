"""`account` (S1 §3.1) — one row per (customer, role, security) the ledger posts against.

Each account has exactly one **dimension** (`money` or `units`), determined by its `role` and
never independently settable (§3.1). `Account.create()` is the only supported constructor for
that reason: it derives `dimension` from `role` via `_ROLE_DIMENSION` so application code never
passes a `dimension` that could disagree with the role. `ck_account_role_dimension` backstops the
same rule at the database, in case a row is ever written by a path that bypasses this factory.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, CheckConstraint, String, event
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class AccountRole(StrEnum):
    """Extensible per S1 §3.1: S5 adds `dividend_receivable`/`realized_gain_loss`; S10 adds the
    performance-fee accounts (ADR 10). Only the roles S1 itself needs are defined here."""

    CASH = "cash"
    CUSTOMER_EQUITY = "customer_equity"
    POSITION_UNITS = "position_units"
    POSITION_COST = "position_cost"
    FEES_EXPENSE = "fees_expense"
    DIVIDEND_INCOME = "dividend_income"


class AccountDimension(StrEnum):
    MONEY = "money"
    UNITS = "units"


_ROLE_DIMENSION: dict[AccountRole, AccountDimension] = {
    AccountRole.CASH: AccountDimension.MONEY,
    AccountRole.CUSTOMER_EQUITY: AccountDimension.MONEY,
    AccountRole.POSITION_UNITS: AccountDimension.UNITS,
    AccountRole.POSITION_COST: AccountDimension.MONEY,
    AccountRole.FEES_EXPENSE: AccountDimension.MONEY,
    AccountRole.DIVIDEND_INCOME: AccountDimension.MONEY,
}


class Account(Base):
    __tablename__ = "account"
    __table_args__ = (
        CheckConstraint(
            "(role = 'cash' AND dimension = 'money') OR "
            "(role = 'customer_equity' AND dimension = 'money') OR "
            "(role = 'position_units' AND dimension = 'units') OR "
            "(role = 'position_cost' AND dimension = 'money') OR "
            "(role = 'fees_expense' AND dimension = 'money') OR "
            "(role = 'dividend_income' AND dimension = 'money')",
            name="role_dimension",
        ),
        CheckConstraint("currency = 'USD'", name="currency_usd"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Nullable: null only for house accounts (fees_expense, dividend_income) with no owning
    # customer (S1 §3.1).
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # No FK: the securities catalogue is S5's to define. Set only for position_units/
    # position_cost roles (§3.1) -- enforced by Account.create(), not a DB constraint, since no
    # securities table exists yet for a CHECK or FK to reference.
    security_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[AccountRole] = mapped_column(
        SQLAlchemyEnum(AccountRole, name="account_role", values_callable=enum_values),
        nullable=False,
    )
    dimension: Mapped[AccountDimension] = mapped_column(
        SQLAlchemyEnum(AccountDimension, name="account_dimension", values_callable=enum_values),
        nullable=False,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    @classmethod
    def create(
        cls,
        role: AccountRole,
        *,
        customer_id: uuid.UUID | None = None,
        security_id: uuid.UUID | None = None,
    ) -> Account:
        """The only supported way to build an `Account` -- derives `dimension` from `role` so it
        can never be set independently (§3.1)."""
        if role in (AccountRole.POSITION_UNITS, AccountRole.POSITION_COST) and security_id is None:
            raise ValueError(f"{role} accounts require a security_id")
        return cls(
            role=role,
            dimension=_ROLE_DIMENSION[role],
            customer_id=customer_id,
            security_id=security_id,
            currency="USD",
        )


# S0 §7.3's role-aware tenant-isolation RLS policy (ADR 17), the same shape as `customer`
# (`app/models/identity/customer.py`). A house account (`customer_id IS NULL`) is excluded from a
# customer session's rows -- it has no owning customer to match, which is correct: a customer
# never reads a house account directly.
event.listen(
    Account.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE account ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON account
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    Account.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON account;"
        "ALTER TABLE account DISABLE ROW LEVEL SECURITY;"
    ),
)


class AccountRepository(BaseRepository[Account]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Account, customer_id_column=Account.customer_id)

    def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return self.session.query(Account).filter_by(id=account_id).first()
