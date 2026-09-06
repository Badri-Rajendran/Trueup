"""`account` (S1 §3.1) — one row per (customer, role, security) the ledger posts against.

`dimension` is derived from `role` by `Account.create()`, never independently settable; backstopped
at the DB by a `CheckConstraint`.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, CheckConstraint, Index, String, event
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class AccountRole(StrEnum):
    """Extensible per S1 §3.1; later specs (S2, S5, S10) add roles for their own domains."""

    CASH = "cash"
    CUSTOMER_EQUITY = "customer_equity"
    POSITION_UNITS = "position_units"
    POSITION_COST = "position_cost"
    FEES_EXPENSE = "fees_expense"
    DIVIDEND_INCOME = "dividend_income"
    CUSTOMER_RECEIVABLE = "customer_receivable"
    DIVIDEND_RECEIVABLE = "dividend_receivable"
    REALIZED_GAIN_LOSS = "realized_gain_loss"
    FEES_ACCRUED_PAYABLE = "fees_accrued_payable"
    FEE_REVENUE_ACCRUED = "fee_revenue_accrued"
    FEE_REVENUE_COLLECTED = "fee_revenue_collected"


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
    AccountRole.CUSTOMER_RECEIVABLE: AccountDimension.MONEY,
    AccountRole.DIVIDEND_RECEIVABLE: AccountDimension.MONEY,
    AccountRole.REALIZED_GAIN_LOSS: AccountDimension.MONEY,
    AccountRole.FEES_ACCRUED_PAYABLE: AccountDimension.MONEY,
    AccountRole.FEE_REVENUE_ACCRUED: AccountDimension.MONEY,
    AccountRole.FEE_REVENUE_COLLECTED: AccountDimension.MONEY,
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
            "(role = 'dividend_income' AND dimension = 'money') OR "
            "(role = 'customer_receivable' AND dimension = 'money') OR "
            "(role = 'dividend_receivable' AND dimension = 'money') OR "
            "(role = 'realized_gain_loss' AND dimension = 'money') OR "
            "(role = 'fees_accrued_payable' AND dimension = 'money') OR "
            "(role = 'fee_revenue_accrued' AND dimension = 'money') OR "
            "(role = 'fee_revenue_collected' AND dimension = 'money')",
            name="role_dimension",
        ),
        CheckConstraint("currency = 'USD'", name="currency_usd"),
        # S12 §3: every cash-policy/balance query filters on (customer_id, role).
        Index("ix_account_customer_role", "customer_id", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Null only for house accounts (fees_expense, dividend_income) with no owning customer (S1 §3.1).
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # No FK (predates Security, S4 §3.3). Set only for position_units/position_cost roles.
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
        """The only supported way to build an `Account`; derives `dimension` from `role` (§3.1)."""
        if role in (AccountRole.POSITION_UNITS, AccountRole.POSITION_COST) and security_id is None:
            raise ValueError(f"{role} accounts require a security_id")
        return cls(
            role=role,
            dimension=_ROLE_DIMENSION[role],
            customer_id=customer_id,
            security_id=security_id,
            currency="USD",
        )


# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17); house accounts are excluded from a
# customer session's rows.
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
