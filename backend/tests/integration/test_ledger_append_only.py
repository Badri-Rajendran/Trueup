"""S1 §7 item 3 append-only: `UPDATE`/`DELETE` fail under `DbRole.APP`'s revoked grants (S1 §6),
and a correction round-trip leaves the original row byte-for-byte unchanged."""

from __future__ import annotations

import copy
from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.core.db import DbRole
from app.core.money import Money
from app.core.uow import SessionRole, UnitOfWork
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.services.ledger.posting_service import PostingLeg, PostingService
from tests.integration.conftest import insert_customer, insert_inbound_event

pytestmark = pytest.mark.usefixtures("ledger_tables")


class _LedgerLikeUow:
    def __init__(self, session):
        self.session = session

        class _Repo:
            def __init__(self, session):
                self._session = session

            def add(self, obj):
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


def _open_deposit(session, customer_id) -> tuple[JournalEntry, list[Posting]]:
    event_id = insert_inbound_event(session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    session.add_all([cash, equity])
    session.flush()

    service = PostingService(_LedgerLikeUow(session))
    entry = service.post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("1000.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-1000.00")),
        ],
    )
    session.commit()
    postings = session.query(Posting).filter_by(journal_entry_id=entry.id).all()
    return entry, postings


def test_app_role_cannot_update_a_journal_entry(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    entry, _postings = _open_deposit(db_committing, customer_id)

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(
            JournalEntry.__table__.update()
            .where(JournalEntry.id == entry.id)
            .values(memo="mutated")
        )


def test_app_role_cannot_delete_a_journal_entry(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    entry, _postings = _open_deposit(db_committing, customer_id)

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(JournalEntry.__table__.delete().where(JournalEntry.id == entry.id))


def test_app_role_cannot_update_a_posting(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    _entry, postings = _open_deposit(db_committing, customer_id)

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(
            Posting.__table__.update()
            .where(Posting.id == postings[0].id)
            .values(amount_money=Money("1.00"))
        )


def test_app_role_cannot_delete_a_posting(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    _entry, postings = _open_deposit(db_committing, customer_id)

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(Posting.__table__.delete().where(Posting.id == postings[0].id))


def test_correction_round_trip_leaves_the_original_row_byte_for_byte_unchanged(
    db_committing,
) -> None:
    customer_id = insert_customer(db_committing)
    original, _postings = _open_deposit(db_committing, customer_id)
    before = copy.deepcopy(
        {c.name: getattr(original, c.name) for c in JournalEntry.__table__.columns}
    )

    cash = db_committing.query(Account).filter_by(
        customer_id=customer_id, role=AccountRole.CASH
    ).one()
    equity = db_committing.query(Account).filter_by(
        customer_id=customer_id, role=AccountRole.CUSTOMER_EQUITY
    ).one()

    correcting_event_id = insert_inbound_event(db_committing)
    service = PostingService(_LedgerLikeUow(db_committing))
    correction = service.correct(
        original=original,
        effective_date=date(2026, 9, 1),
        source_event_id=correcting_event_id,
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("900.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-900.00")),
        ],
        reason="corrected deposit amount",
    )
    db_committing.commit()

    reloaded_original = db_committing.execute(
        select(JournalEntry).where(JournalEntry.id == original.id)
    ).scalar_one()
    after = {c.name: getattr(reloaded_original, c.name) for c in JournalEntry.__table__.columns}

    assert after == before
    assert after["superseded_by"] is None  # original never touched
    assert correction.superseded_by == original.id  # new row carries the link
    assert correction.entry_type == original.entry_type == JournalEntryType.DEPOSIT
