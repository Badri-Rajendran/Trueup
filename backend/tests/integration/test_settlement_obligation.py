"""S1 §7 item 4: settlement never mutates the ledger. `confirmed` writes zero new postings
(ADR 2); a second transition off a terminal row is rejected by both app and DB trigger (S1 §6)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import (
    SettlementObligation,
    SettlementObligationRepository,
    SettlementObligationStatus,
)
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


class _LedgerLikeUow:
    def __init__(self, session):
        self.session = session


def _open_obligation(session, customer_id) -> SettlementObligation:
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    session.add(cash)
    session.flush()

    entry_event_id = insert_inbound_event(session)
    from app.models.ledger.journal_entry import JournalEntry, JournalEntryType

    entry = JournalEntry(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=entry_event_id,
    )
    session.add(entry)
    session.flush()

    obligation_event_id = insert_inbound_event(session)
    obligation = SettlementObligation(
        journal_entry_id=entry.id,
        account_id=cash.id,
        amount_money=Money("1000.00"),
        expected_settlement_date=date(2026, 9, 3),
        source_event_id=obligation_event_id,
    )
    session.add(obligation)
    session.flush()
    return obligation


def test_confirming_an_obligation_writes_zero_new_posting_rows(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    obligation = _open_obligation(db_committing, customer_id)
    db_committing.commit()

    postings_before = db_committing.execute(select(func.count(Posting.id))).scalar_one()

    repo = SettlementObligationRepository(_LedgerLikeUow(db_committing))
    repo.confirm(obligation, confirmed_at=datetime.now(UTC))
    db_committing.commit()

    postings_after = db_committing.execute(select(func.count(Posting.id))).scalar_one()

    assert postings_after == postings_before == 0
    db_committing.refresh(obligation)
    assert obligation.status is SettlementObligationStatus.CONFIRMED
    assert obligation.confirmed_at is not None


def test_repository_rejects_a_second_transition_on_an_already_terminal_obligation(
    db_committing,
) -> None:
    customer_id = insert_customer(db_committing)
    obligation = _open_obligation(db_committing, customer_id)
    repo = SettlementObligationRepository(_LedgerLikeUow(db_committing))
    repo.confirm(obligation, confirmed_at=datetime.now(UTC))
    db_committing.commit()

    with pytest.raises(ValueError, match="already"):
        repo.confirm(obligation, confirmed_at=datetime.now(UTC))


def test_database_trigger_rejects_a_second_transition_even_bypassing_the_repository(
    db_committing,
) -> None:
    """The database itself also rejects this, via `settlement_obligation_before_update` (S1 §6)."""
    customer_id = insert_customer(db_committing)
    obligation = _open_obligation(db_committing, customer_id)
    obligation.status = SettlementObligationStatus.CONFIRMED
    obligation.confirmed_at = datetime.now(UTC)
    db_committing.commit()

    obligation.failure_reason = "attempted re-transition"
    obligation.status = SettlementObligationStatus.FAILED
    with pytest.raises(DBAPIError):
        db_committing.commit()
