"""Row-Level Security on `posting` (S1 §3.3, S0 §7.3, ADR 17) — `posting` needed its own
role-aware policy since its tenant key (`customer_id`) is denormalized rather than native. Both
required tests, matching `tests/integration/test_identity_rls.py`'s own pattern for `customer`:

1. A `customer`-role session cannot read another customer's postings, **even with the
   application-layer guard disabled** (a raw `select(Posting)`, no `PostingRepository` filter) --
   proving the database is the real control.
2. An `adviser`-role session *can* read across customers under the same policy -- proving the
   role-aware branch actually works, not just the restrictive one.

Both go through the `app` role's own credential (`DbRole.APP`, no `BYPASSRLS`).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.core.db import DbRole
from app.core.money import Money
from app.core.uow import SessionRole, UnitOfWork
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
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


def _deposit(session, customer_id: uuid.UUID) -> None:
    event_id = insert_inbound_event(session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    session.add_all([cash, equity])
    session.flush()

    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("500.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-500.00")),
        ],
    )


def _insert_two_customers_with_postings(db_committing) -> tuple[uuid.UUID, uuid.UUID]:
    customer_a_id = insert_customer(db_committing)
    customer_b_id = insert_customer(db_committing)
    _deposit(db_committing, customer_a_id)
    _deposit(db_committing, customer_b_id)
    db_committing.commit()
    return customer_a_id, customer_b_id


def test_customer_session_cannot_see_another_customers_postings_even_without_the_app_guard(
    db_committing,
) -> None:
    customer_a_id, customer_b_id = _insert_two_customers_with_postings(db_committing)

    with UnitOfWork(
        customer_id=customer_a_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        visible_customer_ids = {
            row.customer_id for row in uow.session.execute(select(Posting)).scalars().all()
        }
    assert visible_customer_ids == {customer_a_id}
    assert customer_b_id not in visible_customer_ids


def test_adviser_session_can_read_postings_across_customers_under_the_same_rls_policy(
    db_committing,
) -> None:
    customer_a_id, customer_b_id = _insert_two_customers_with_postings(db_committing)

    with UnitOfWork(customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP) as uow:
        visible_customer_ids = {
            row.customer_id for row in uow.session.execute(select(Posting)).scalars().all()
        }

    assert {customer_a_id, customer_b_id} <= visible_customer_ids


def test_admin_session_can_also_read_across_customers(db_committing) -> None:
    """`admin` is the other branch of the `IN ('adviser', 'admin')` check -- covered separately
    so a policy bug scoped to only one literal would not otherwise be caught."""
    customer_a_id, customer_b_id = _insert_two_customers_with_postings(db_committing)

    with UnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow:
        visible_customer_ids = {
            row.customer_id for row in uow.session.execute(select(Posting)).scalars().all()
        }

    assert {customer_a_id, customer_b_id} <= visible_customer_ids


def test_customer_session_cannot_see_another_customers_account_row(db_committing) -> None:
    """`account`'s own policy (§3.1), same shape -- covered once here since `posting`'s is the
    one S1 §3.3 calls out as needing its own denormalization-aware version."""
    customer_a_id = insert_customer(db_committing)
    customer_b_id = insert_customer(db_committing)
    account_a = Account.create(AccountRole.CASH, customer_id=customer_a_id)
    account_b = Account.create(AccountRole.CASH, customer_id=customer_b_id)
    db_committing.add_all([account_a, account_b])
    db_committing.commit()

    with UnitOfWork(
        customer_id=customer_a_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        visible_ids = {row.id for row in uow.session.execute(select(Account)).scalars().all()}

    assert visible_ids == {account_a.id}
