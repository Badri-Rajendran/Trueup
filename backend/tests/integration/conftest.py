"""Shared fixtures for `tests/integration/`: S1 ledger tables and the engine registry (S0 §5)."""

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
    """Populates the engine registry `UnitOfWork`'s default session_factory needs."""
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def ledger_tables(owner_engine: Engine):
    """Per-test S1 table setup. Per-table create/drop, not `create_all()` (see `test_ops_spine.py`);
    teardown uses `DROP ... CASCADE` since other fixtures may hold a live FK into `customer`."""
    for table in LEDGER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def insert_customer(session: Session) -> uuid.UUID:
    """Owner-role insert; pure test setup."""
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    session.add(customer)
    session.flush()
    return customer.id


def insert_inbound_event(session: Session, *, source_event_id: str | None = None) -> uuid.UUID:
    """Pure setup: every journal_entry/settlement_obligation traces to one inbound_event."""
    event = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=source_event_id or str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    session.add(event)
    session.flush()
    return event.id
