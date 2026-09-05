"""`AccountRole.CUSTOMER_RECEIVABLE` (S2 §5.2 step 4, FR-6) -- S1 §3.1's first real extension of
the `role` enum. Proves the database, not just `Account.create()`, accepts the new role/dimension
pairing: the `ck_account_role_dimension` CHECK constraint (updated alongside the enum) and the
`posting_before_insert` trigger both need to agree a `customer_receivable` account is
money-dimensioned.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.money import Money
from app.models.ledger.account import Account, AccountDimension, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


def test_customer_receivable_account_commits_against_the_updated_check_constraint(
    db_committing,
) -> None:
    customer_id = insert_customer(db_committing)
    receivable = Account.create(AccountRole.CUSTOMER_RECEIVABLE, customer_id=customer_id)
    db_committing.add(receivable)
    db_committing.commit()  # must not raise -- proves the DB-level CHECK accepts the new pairing

    db_committing.refresh(receivable)
    assert receivable.dimension is AccountDimension.MONEY


def test_posting_trigger_accepts_a_money_leg_against_a_customer_receivable_account(
    db_committing,
) -> None:
    customer_id = insert_customer(db_committing)
    receivable = Account.create(AccountRole.CUSTOMER_RECEIVABLE, customer_id=customer_id)
    db_committing.add(receivable)
    db_committing.flush()

    event_id = insert_inbound_event(db_committing)
    entry = JournalEntry(
        entry_type=JournalEntryType.CORRECTION,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
    )
    db_committing.add(entry)
    db_committing.flush()

    posting = Posting(
        journal_entry_id=entry.id, account_id=receivable.id, amount_money=Money("50.00")
    )
    db_committing.add(posting)
    db_committing.flush()
    db_committing.refresh(posting)

    assert posting.customer_id == customer_id
