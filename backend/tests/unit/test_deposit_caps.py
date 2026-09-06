"""`check_deposit_caps` / `build_ach_return_correction_legs` (S2 §5.2 steps 2/4) — pure logic, no
database (S2 §8)."""

from __future__ import annotations

import uuid

import pytest

from app.core.money import Money
from app.services.identity.deposit_service import (
    DepositCapExceededError,
    build_ach_return_correction_legs,
    check_deposit_caps,
)

CAP_PER_TRANSACTION = Money("25000.00")
CAP_PER_DAY = Money("50000.00")


def test_amount_within_both_caps_passes() -> None:
    check_deposit_caps(
        Money("1000.00"),
        deposited_today=Money("0.00"),
        cap_per_transaction=CAP_PER_TRANSACTION,
        cap_per_day=CAP_PER_DAY,
    )


def test_amount_over_the_per_transaction_cap_is_rejected() -> None:
    with pytest.raises(DepositCapExceededError) as exc_info:
        check_deposit_caps(
            Money("25000.01"),
            deposited_today=Money("0.00"),
            cap_per_transaction=CAP_PER_TRANSACTION,
            cap_per_day=CAP_PER_DAY,
        )
    assert exc_info.value.cap == "per_transaction"


def test_amount_at_exactly_the_per_transaction_cap_is_allowed() -> None:
    check_deposit_caps(
        CAP_PER_TRANSACTION,
        deposited_today=Money("0.00"),
        cap_per_transaction=CAP_PER_TRANSACTION,
        cap_per_day=CAP_PER_DAY,
    )


def test_amount_pushing_the_daily_aggregate_over_the_cap_is_rejected() -> None:
    with pytest.raises(DepositCapExceededError) as exc_info:
        check_deposit_caps(
            Money("1000.00"),
            deposited_today=Money("49500.00"),
            cap_per_transaction=CAP_PER_TRANSACTION,
            cap_per_day=CAP_PER_DAY,
        )
    assert exc_info.value.cap == "per_day"


def test_amount_at_exactly_the_remaining_daily_headroom_is_allowed() -> None:
    check_deposit_caps(
        Money("500.00"),
        deposited_today=Money("49500.00"),
        cap_per_transaction=CAP_PER_TRANSACTION,
        cap_per_day=CAP_PER_DAY,
    )


def test_correction_legs_move_the_amount_from_cash_to_receivable_and_balance_to_zero() -> None:
    cash_account_id = uuid.uuid4()
    receivable_account_id = uuid.uuid4()
    amount = Money("500.00")

    legs = build_ach_return_correction_legs(
        cash_account_id=cash_account_id, receivable_account_id=receivable_account_id, amount=amount
    )

    assert len(legs) == 2
    cash_leg = next(leg for leg in legs if leg.account_id == cash_account_id)
    receivable_leg = next(leg for leg in legs if leg.account_id == receivable_account_id)
    assert cash_leg.amount_money == -amount
    assert receivable_leg.amount_money == amount
    assert (cash_leg.amount_money + receivable_leg.amount_money) == Money("0.00")
