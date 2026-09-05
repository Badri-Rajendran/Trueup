"""`Account.create()` (S1 §3.1) -- pure, no database: dimension is derived from role, never
independently settable."""

from __future__ import annotations

import uuid

import pytest

from app.models.ledger.account import Account, AccountDimension, AccountRole


@pytest.mark.parametrize(
    ("role", "expected_dimension"),
    [
        (AccountRole.CASH, AccountDimension.MONEY),
        (AccountRole.CUSTOMER_EQUITY, AccountDimension.MONEY),
        (AccountRole.POSITION_COST, AccountDimension.MONEY),
        (AccountRole.FEES_EXPENSE, AccountDimension.MONEY),
        (AccountRole.DIVIDEND_INCOME, AccountDimension.MONEY),
        (AccountRole.POSITION_UNITS, AccountDimension.UNITS),
    ],
)
def test_create_derives_dimension_from_role(
    role: AccountRole, expected_dimension: AccountDimension
) -> None:
    needs_security = role in (AccountRole.POSITION_UNITS, AccountRole.POSITION_COST)
    security_id = uuid.uuid4() if needs_security else None
    account = Account.create(role, customer_id=uuid.uuid4(), security_id=security_id)
    assert account.dimension is expected_dimension


def test_create_requires_a_security_id_for_position_units() -> None:
    with pytest.raises(ValueError, match="security_id"):
        Account.create(AccountRole.POSITION_UNITS, customer_id=uuid.uuid4())


def test_create_requires_a_security_id_for_position_cost() -> None:
    with pytest.raises(ValueError, match="security_id"):
        Account.create(AccountRole.POSITION_COST, customer_id=uuid.uuid4())


def test_create_allows_a_house_account_with_no_customer_id() -> None:
    account = Account.create(AccountRole.FEES_EXPENSE)
    assert account.customer_id is None
    assert account.dimension is AccountDimension.MONEY


def test_create_always_sets_currency_to_usd() -> None:
    account = Account.create(AccountRole.CASH, customer_id=uuid.uuid4())
    assert account.currency == "USD"
