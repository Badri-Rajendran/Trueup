"""`RestatementService`'s S10 hook: a restatement on an already-charged period inserts a
`fee_restatement_disclosure` row without reopening the charge (§6, FR-47)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.money import Money
from app.core.uow import SessionRole
from app.models.fees.fee_charge import FeeCharge, FeeChargeStatus
from app.models.fees.fee_restatement_disclosure import FeeRestatementDisclosure
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.models.restatement.restatement_event import RestatementEvent, RestatementTriggerType
from app.services.fees.fee_restatement_disclosure_service import FeeRestatementDisclosureService
from app.services.fees.uow import FeesUnitOfWork
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.restatement.restatement_service import RestatementService
from app.services.restatement.snapshot_service import SnapshotService
from tests.integration.conftest import LEDGER_TABLES, insert_customer, insert_inbound_event

FEES_RESTATEMENT_TABLES = [
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
    PublishedSnapshot.__table__,
    RestatementEvent.__table__,
    FeeCharge.__table__,
    FeeRestatementDisclosure.__table__,
]


@pytest.fixture
def restatement_tables(owner_engine):
    for table in LEDGER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    for table in FEES_RESTATEMENT_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(FEES_RESTATEMENT_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("restatement_tables")


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


def _fees_uow(session, *, customer_id: uuid.UUID) -> FeesUnitOfWork:
    return FeesUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, session_factory=lambda: session
    )


def test_restatement_touching_an_already_charged_period_inserts_a_disclosure(
    db_committing,
) -> None:
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
    }
    db_committing.add_all(accounts.values())
    db_committing.flush()

    period_start, period_end = date(2026, 8, 1), date(2026, 8, 31)
    event_id = insert_inbound_event(db_committing)
    PostingService(_LedgerLikeUow(db_committing)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=period_start,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["cash"].id, amount_money=Money("5000.00")),
            PostingLeg(account_id=accounts["customer_equity"].id, amount_money=Money("-5000.00")),
        ],
    )
    db_committing.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        SnapshotService(uow).publish(customer_id, period_start, period_end)
        uow.commit()

    fee_charge = FeeCharge(
        customer_id=customer_id,
        billing_period_start=period_start,
        billing_period_end=period_end,
        total_accrued=Money("10.00"),
        as_published_watermark=datetime.now(UTC),
        status=FeeChargeStatus.SUCCEEDED,
    )
    db_committing.add(fee_charge)
    db_committing.commit()

    correction_event_id = insert_inbound_event(db_committing)
    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        checker = FeeRestatementDisclosureService(uow)
        service = RestatementService(uow, fee_disclosure_checker=checker)
        service.restate(
            customer_id=customer_id,
            affected_date=period_start,
            trigger_type=RestatementTriggerType.MANUAL_CORRECTION,
            source_event_id=correction_event_id,
        )
        uow.commit()

    disclosures = (
        db_committing.query(FeeRestatementDisclosure).filter_by(customer_id=customer_id).all()
    )
    assert len(disclosures) == 1
    assert disclosures[0].fee_charge_id == fee_charge.id

    # Fresh query, not refresh(): `_fees_uow`'s exit detaches `fee_charge` from the identity map.
    reloaded_charge = db_committing.query(FeeCharge).filter_by(id=fee_charge.id).one()
    assert reloaded_charge.status is FeeChargeStatus.SUCCEEDED  # never reopened (FR-47)
    assert reloaded_charge.total_accrued == Money("10.00")  # never adjusted


def test_restatement_with_no_disclosure_checker_configured_does_not_raise(db_committing) -> None:
    """Existing trigger sites construct `RestatementService` with no checker; must keep working."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
    }
    db_committing.add_all(accounts.values())
    db_committing.flush()
    db_committing.commit()

    correction_event_id = insert_inbound_event(db_committing)
    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        service = RestatementService(uow)
        service.restate(
            customer_id=customer_id,
            affected_date=date(2026, 8, 1),
            trigger_type=RestatementTriggerType.MANUAL_CORRECTION,
            source_event_id=correction_event_id,
        )
        uow.commit()
