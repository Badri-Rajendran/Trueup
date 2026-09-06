"""Shared fixtures for `tests/integration/` -- S1's ledger tables and the engine registry every
ledger integration test needs (S0 §5's `UnitOfWork` reads engines from the process-wide registry,
not from a fixture directly)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from app.extensions import dispose_engines, init_engines
from app.models.identity.customer import Customer
from app.models.ledger.account import Account
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.inbound_event import InboundEvent, InboundEventSource

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from app.config import Settings

# Dependency order: FKs point earlier in this list.
LEDGER_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
]


@pytest.fixture(autouse=True)
def engines(test_settings: Settings) -> None:
    """`UnitOfWork`'s default session_factory path needs the engine registry populated."""
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def ledger_tables(owner_engine: Engine):
    """Self-sufficient per-test table setup for S1's schema plus the tables it FKs to
    (`customer`, `inbound_event`) -- matching `tests/integration/test_ops_spine.py`'s
    `ops_tables` fixture. Per-table `.create()`/`.drop()`, not `Base.metadata.create_all()`: the
    latter dispatches MetaData-level enum DDL events for every native-Postgres-enum column across
    the whole shared metadata regardless of the `tables=` filter, which fails once multiple
    domains' enums coexist on it (see that fixture's own comment for the full explanation).

    Teardown uses `DROP ... CASCADE`, not SQLAlchemy's own `.drop()`: another test file's
    session-scoped fixture (e.g. `test_orders.py`'s `order`/`approval_hold`) may have a live FK
    into `customer` at the moment this per-test fixture tears down, and a plain `.drop()` fails
    hard on `DependentObjectsStillExist` in that case -- a real, previously-documented cascade
    (5 known teardown-only errors, `DECISION-LOG.md`). CASCADE removes just that dependent FK
    constraint, never a table outside this fixture's own list, matching
    `test_fee_charge_schema.py`'s identical fix for the same shape of problem.
    """
    for table in LEDGER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def insert_customer(session: Session) -> uuid.UUID:
    """Owner-role insert -- pure setup for a ledger test, not part of what it proves."""
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    session.add(customer)
    session.flush()
    return customer.id


def insert_inbound_event(session: Session, *, source_event_id: str | None = None) -> uuid.UUID:
    """Every journal_entry/settlement_obligation traces back to one inbound_event (S1 §3.2's
    idempotency tie-in) -- pure setup, standing in for whatever real intake produced it."""
    event = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=source_event_id or str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    session.add(event)
    session.flush()
    return event.id
