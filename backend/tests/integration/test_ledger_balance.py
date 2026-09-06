"""S1 §7 item 1: the money-sum-to-zero invariant, both at the app layer (`PostingService`) and
the DB's deferred `ledger_balance` trigger at COMMIT (§3.4, ADR 17)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.money import Money, Units
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.services.ledger.posting_service import (
    PostingLeg,
    PostingService,
    UnbalancedEntryError,
)
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


def _open_accounts(session, customer_id):
    security_id = uuid.uuid4()
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
        "position_units": Account.create(
            AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security_id
        ),
        "position_cost": Account.create(
            AccountRole.POSITION_COST, customer_id=customer_id, security_id=security_id
        ),
        "fees_expense": Account.create(AccountRole.FEES_EXPENSE),
    }
    session.add_all(accounts.values())
    session.flush()
    return accounts


class _FakeLedgerUow:
    """Just enough of `LedgerUnitOfWork`'s surface for `PostingService`."""

    def __init__(self, session):
        self.session = session

        class _Repo:
            def __init__(self, session):
                self._session = session

            def add(self, obj):
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


def test_posting_service_rejects_an_unbalanced_entry_before_it_reaches_the_database(
    db_session,
) -> None:
    customer_id = insert_customer(db_session)
    event_id = insert_inbound_event(db_session)
    accounts = _open_accounts(db_session, customer_id)
    service = PostingService(_FakeLedgerUow(db_session))

    with pytest.raises(UnbalancedEntryError):
        service.post(
            entry_type=JournalEntryType.DEPOSIT,
            effective_date=date(2026, 9, 1),
            source_event_id=event_id,
            legs=[
                PostingLeg(account_id=accounts["cash"].id, amount_money=Money("1000.00")),
                PostingLeg(
                    account_id=accounts["customer_equity"].id, amount_money=Money("-999.00")
                ),
            ],
        )


def test_ledger_balance_trigger_fires_at_commit_not_at_flush(db_committing) -> None:
    """S1 §7 item 1: the database itself rejects an out-of-balance entry, at COMMIT."""
    customer_id = insert_customer(db_committing)
    event_id = insert_inbound_event(db_committing)
    accounts = _open_accounts(db_committing, customer_id)

    entry = JournalEntry(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
    )
    db_committing.add(entry)
    db_committing.flush()

    # Deliberately unbalanced, inserted directly -- no PostingService involved.
    db_committing.add(
        Posting(
            journal_entry_id=entry.id,
            account_id=accounts["cash"].id,
            amount_money=Money("1000.00"),
        )
    )
    db_committing.add(
        Posting(
            journal_entry_id=entry.id,
            account_id=accounts["customer_equity"].id,
            amount_money=Money("-999.00"),
        )
    )
    db_committing.flush()  # must NOT raise -- trigger is deferred to COMMIT.

    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


@pytest.mark.parametrize(
    "build_legs",
    [
        pytest.param(
            lambda a: [
                PostingLeg(account_id=a["position_units"].id, quantity_units=Units("10")),
                PostingLeg(account_id=a["position_cost"].id, amount_money=Money("1500.00")),
                PostingLeg(account_id=a["fees_expense"].id, amount_money=Money("1.00")),
                PostingLeg(account_id=a["cash"].id, amount_money=Money("-1501.00")),
            ],
            id="buy_10_aapl_at_150_plus_1_fee",
        ),
        pytest.param(
            lambda a: [
                PostingLeg(account_id=a["cash"].id, amount_money=Money("1000.00")),
                PostingLeg(account_id=a["customer_equity"].id, amount_money=Money("-1000.00")),
            ],
            id="deposit_1000",
        ),
        pytest.param(
            lambda a: [
                PostingLeg(account_id=a["position_units"].id, quantity_units=Units("20")),
            ],
            id="2_for_1_split_units_only_no_money_legs",
        ),
    ],
)
def test_balanced_entries_from_the_spec_commit_cleanly(db_committing, build_legs) -> None:
    customer_id = insert_customer(db_committing)
    event_id = insert_inbound_event(db_committing)
    accounts = _open_accounts(db_committing, customer_id)
    service = PostingService(_FakeLedgerUow(db_committing))

    service.post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=build_legs(accounts),
    )

    db_committing.commit()  # must not raise


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    other_amounts=st.lists(
        st.decimals(min_value="0.01", max_value="100000", places=4, allow_nan=False),
        min_size=1,
        max_size=3,
        unique=True,
    )
)
def test_arbitrary_valid_entries_always_sum_to_zero_and_commit(
    db_committing, other_amounts: list[Decimal]
) -> None:
    """S1 §7 item 1: property-based -- every balanced entry, any leg count or amount, commits
    and sums to exactly zero (§3.4)."""
    customer_id = insert_customer(db_committing)
    event_id = insert_inbound_event(db_committing)
    accounts = _open_accounts(db_committing, customer_id)
    other_account_keys = ["customer_equity", "position_cost", "fees_expense"]

    other_legs = [
        PostingLeg(account_id=accounts[key].id, amount_money=Money(amount))
        for key, amount in zip(other_account_keys, other_amounts, strict=False)
    ]
    balancing_amount = -sum((leg.amount_money for leg in other_legs), Money("0.00"))
    legs = [
        *other_legs,
        PostingLeg(account_id=accounts["cash"].id, amount_money=balancing_amount),
    ]

    service = PostingService(_FakeLedgerUow(db_committing))
    entry = service.post(
        entry_type=JournalEntryType.CORRECTION,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=legs,
    )
    db_committing.commit()  # must not raise -- DB trigger must agree the entry balances

    total = db_committing.execute(
        select(func.coalesce(func.sum(Posting.amount_money), 0)).where(
            Posting.journal_entry_id == entry.id
        )
    ).scalar_one()
    assert Money(total) == Money("0.00")
