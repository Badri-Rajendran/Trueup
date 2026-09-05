"""S1 §7 item 2 -- units never cross into money.

Three layers: the `CHECK` constraint rejects a posting with both (or neither) column set; the
`posting_before_insert` trigger rejects a posting whose non-null column disagrees with its
account's dimension; and separately, the trigger sets `posting.customer_id` from the target
account regardless of what the insert statement supplied -- proving the trigger, not the caller,
is the source of truth (S1 §3.3).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.exc import DataError, IntegrityError, InternalError, ProgrammingError

from app.core.money import Money, Units
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


def _open_entry(session, customer_id) -> uuid.UUID:
    event_id = insert_inbound_event(session)
    entry = JournalEntry(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
    )
    session.add(entry)
    session.flush()
    return entry.id


def test_check_rejects_a_posting_with_both_columns_set(db_session) -> None:
    """Whichever leg the target account's dimension doesn't match, `posting_before_insert` (§3.3)
    raises first -- so this is rejected before the `CHECK` even gets a chance to run, same as the
    "wrong dimension" tests below. Either way, the row is rejected at the database, which is what
    this test proves; `ProgrammingError` (the trigger) and `IntegrityError` (the `CHECK`) are both
    acceptable outcomes."""
    customer_id = insert_customer(db_session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    db_session.add(cash)
    db_session.flush()
    entry_id = _open_entry(db_session, customer_id)

    db_session.add(
        Posting(
            journal_entry_id=entry_id,
            account_id=cash.id,
            amount_money=Money("10.00"),
            quantity_units=Units("1"),
        )
    )
    with pytest.raises((IntegrityError, ProgrammingError)):
        db_session.flush()


def test_check_rejects_a_posting_with_neither_column_set(db_session) -> None:
    customer_id = insert_customer(db_session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    db_session.add(cash)
    db_session.flush()
    entry_id = _open_entry(db_session, customer_id)

    db_session.add(Posting(journal_entry_id=entry_id, account_id=cash.id))
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_trigger_rejects_units_posted_against_a_money_account(db_session) -> None:
    customer_id = insert_customer(db_session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    db_session.add(cash)
    db_session.flush()
    entry_id = _open_entry(db_session, customer_id)

    db_session.add(
        Posting(journal_entry_id=entry_id, account_id=cash.id, quantity_units=Units("1"))
    )
    with pytest.raises((InternalError, DataError, IntegrityError, ProgrammingError)):
        db_session.flush()


def test_trigger_rejects_money_posted_against_a_units_account(db_session) -> None:
    customer_id = insert_customer(db_session)
    security_id = uuid.uuid4()
    position_units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security_id
    )
    db_session.add(position_units)
    db_session.flush()
    entry_id = _open_entry(db_session, customer_id)

    db_session.add(
        Posting(
            journal_entry_id=entry_id, account_id=position_units.id, amount_money=Money("1.00")
        )
    )
    with pytest.raises((InternalError, DataError, IntegrityError, ProgrammingError)):
        db_session.flush()


def test_trigger_sets_customer_id_from_the_account_regardless_of_what_the_insert_supplied(
    db_session,
) -> None:
    """The trigger, not the caller, is the source of truth (S1 §3.3): even a deliberately wrong
    `customer_id` supplied on the insert is overwritten from the target account."""
    customer_id = insert_customer(db_session)
    wrong_customer_id = insert_customer(db_session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    db_session.add(cash)
    db_session.flush()
    entry_id = _open_entry(db_session, customer_id)

    posting = Posting(
        journal_entry_id=entry_id,
        account_id=cash.id,
        amount_money=Money("10.00"),
        customer_id=wrong_customer_id,
    )
    db_session.add(posting)
    db_session.flush()
    db_session.refresh(posting)

    assert posting.customer_id == customer_id
    assert posting.customer_id != wrong_customer_id


def test_trigger_sets_customer_id_null_for_a_house_account(db_session) -> None:
    fees_expense = Account.create(AccountRole.FEES_EXPENSE)
    db_session.add(fees_expense)
    db_session.flush()
    customer_id = insert_customer(db_session)
    entry_id = _open_entry(db_session, customer_id)

    posting = Posting(
        journal_entry_id=entry_id, account_id=fees_expense.id, amount_money=Money("1.00")
    )
    db_session.add(posting)
    db_session.flush()
    db_session.refresh(posting)

    assert posting.customer_id is None
