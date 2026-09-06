"""`fee_charge` DB-level invariants: RLS and `as_published_watermark` immutability once set
(S10 §3.4/§9, FR-47)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DataError, IntegrityError, InternalError, ProgrammingError

from app.core.money import Money
from app.models.fees.fee_charge import FeeCharge, FeeChargeStatus
from tests.integration.conftest import LEDGER_TABLES, insert_customer

FEE_CHARGE_TABLES = [*LEDGER_TABLES, FeeCharge.__table__]


@pytest.fixture
def fee_charge_tables(owner_engine):
    for table in FEE_CHARGE_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    # CASCADE: other S10 tables may hold a live FK into `fee_charge` outside this fixture's subset.
    with owner_engine.begin() as connection:
        for table in reversed(FEE_CHARGE_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("fee_charge_tables")


def _charge(customer_id: uuid.UUID, *, watermark: datetime | None = None) -> FeeCharge:
    return FeeCharge(
        customer_id=customer_id,
        billing_period_start=datetime(2026, 8, 1, tzinfo=UTC).date(),
        billing_period_end=datetime(2026, 8, 31, tzinfo=UTC).date(),
        total_accrued=Money("100.00"),
        as_published_watermark=watermark,
        status=FeeChargeStatus.PENDING,
    )


def test_watermark_can_be_set_once_from_null(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    charge = _charge(customer_id)
    db_committing.add(charge)
    db_committing.commit()

    charge.as_published_watermark = datetime(2026, 9, 1, tzinfo=UTC)
    db_committing.commit()  # first assignment from NULL -- must succeed

    db_committing.refresh(charge)
    assert charge.as_published_watermark == datetime(2026, 9, 1, tzinfo=UTC)


def test_watermark_update_is_rejected_once_already_set(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    original_watermark = datetime(2026, 9, 1, tzinfo=UTC)
    charge = _charge(customer_id, watermark=original_watermark)
    db_committing.add(charge)
    db_committing.commit()

    charge.as_published_watermark = datetime(2026, 9, 2, tzinfo=UTC)
    with pytest.raises((InternalError, DataError, IntegrityError, ProgrammingError)):
        db_committing.commit()


def test_updating_an_unrelated_column_is_still_permitted(db_committing) -> None:
    """The trigger only rejects a changed watermark; other columns keep updating (S10 §5)."""
    customer_id = insert_customer(db_committing)
    charge = _charge(customer_id, watermark=datetime(2026, 9, 1, tzinfo=UTC))
    db_committing.add(charge)
    db_committing.commit()

    charge.status = FeeChargeStatus.SUCCEEDED
    charge.stripe_charge_id = "pi_test_123"
    db_committing.commit()

    db_committing.refresh(charge)
    assert charge.status is FeeChargeStatus.SUCCEEDED
    assert charge.stripe_charge_id == "pi_test_123"


def test_a_second_charge_for_the_same_customer_and_period_is_rejected(db_committing) -> None:
    """F5 (S0 §10.1 audit): `uq_fee_charge_customer_period` backstops the read-then-insert
    idempotency check against a concurrent/retried job run."""
    customer_id = insert_customer(db_committing)
    db_committing.add(_charge(customer_id))
    db_committing.commit()

    db_committing.add(_charge(customer_id))
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_a_charge_for_a_different_period_is_still_permitted(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    db_committing.add(_charge(customer_id))
    db_committing.commit()

    other_period = FeeCharge(
        customer_id=customer_id,
        billing_period_start=datetime(2026, 9, 1, tzinfo=UTC).date(),
        billing_period_end=datetime(2026, 9, 30, tzinfo=UTC).date(),
        total_accrued=Money("50.00"),
        status=FeeChargeStatus.PENDING,
    )
    db_committing.add(other_period)
    db_committing.commit()  # must not raise -- a different period is a different key


def test_rewriting_the_watermark_to_the_same_value_is_permitted(db_committing) -> None:
    """`IS DISTINCT FROM`: rewriting the same watermark value is not a mutation attempt."""
    customer_id = insert_customer(db_committing)
    watermark = datetime(2026, 9, 1, tzinfo=UTC)
    charge = _charge(customer_id, watermark=watermark)
    db_committing.add(charge)
    db_committing.commit()

    charge.as_published_watermark = watermark
    charge.status = FeeChargeStatus.SUCCEEDED
    db_committing.commit()  # must not raise
