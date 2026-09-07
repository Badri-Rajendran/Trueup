"""`PortfolioHoldingsService` (Portfolio page redesign, ADR 26 context) against real Postgres --
exercises the same `DriftEvaluationService` + RLS-scoped `RebalanceUnitOfWork` wiring
`GET /api/v1/portfolios/holdings` uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.extensions import dispose_engines, init_engines
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.rebalance.drift_evaluation_service import NoAssignedModelError
from app.services.rebalance.portfolio_holdings_service import PortfolioHoldingsService
from app.services.rebalance.uow import RebalanceUnitOfWork

MARKET_DATE = date(2026, 9, 5)
DRIFT_BAND_PCT = Decimal("0.05")

_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    Security.__table__,
    DailyClose.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
    CustomerModelAssignment.__table__,
]

pytestmark = pytest.mark.usefixtures("_tables")


class _LedgerLikeUow:
    def __init__(self, session: Session) -> None:
        self.session = session

        class _Repo:
            def __init__(self, session: Session) -> None:
                self._session = session

            def add(self, obj: object) -> None:
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _seed_customer(db_committing: Session) -> uuid.UUID:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=KycStatus.approved,
        account_approval_status=AccountApprovalStatus.approved,
    )
    db_committing.add(customer)
    db_committing.flush()
    db_committing.add(CustomerCashLock(customer_id=customer.id))
    db_committing.commit()
    return customer.id


def _insert_event(db_committing: Session) -> uuid.UUID:
    event = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    db_committing.add(event)
    db_committing.flush()
    return event.id


def _holdings(customer_id: uuid.UUID, *, as_of_date: date = MARKET_DATE):
    with RebalanceUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        return PortfolioHoldingsService(uow, drift_band_pct=DRIFT_BAND_PCT).holdings(
            customer_id, as_of_date
        )


def test_raises_when_no_model_assigned(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)

    with pytest.raises(NoAssignedModelError):
        _holdings(customer_id)


def test_holdings_include_units_price_and_drift(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    security = Security(
        symbol="ITG", name="Integration Co.", asset_class=SecurityAssetClass.EQUITY
    )
    db_committing.add(security)
    db_committing.flush()
    db_committing.add(
        DailyClose(
            security_id=security.id,
            market_date=MARKET_DATE,
            close_price=Price("100.00"),
            source=MarketDataSource.LIVE,
            status=DailyCloseStatus.CONFIRMED,
        )
    )
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
    )
    cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
    )
    db_committing.add_all([cash, equity, units, cost])
    db_committing.flush()

    posting = PostingService(_LedgerLikeUow(db_committing))
    posting.post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=MARKET_DATE,
        source_event_id=_insert_event(db_committing),
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-10000.00")),
        ],
    )
    posting.post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=MARKET_DATE,
        source_event_id=_insert_event(db_committing),
        legs=[
            PostingLeg(account_id=units.id, quantity_units=Units("100")),
            PostingLeg(account_id=cost.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=cash.id, amount_money=Money("-10000.00")),
        ],
    )

    model = ModelPortfolio(name="Test Model")
    db_committing.add(model)
    db_committing.flush()
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security.id, weight_pct=Decimal("1.0000")
        )
    )
    db_committing.add(
        CustomerModelAssignment(
            customer_id=customer_id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
        )
    )
    db_committing.commit()

    result = _holdings(customer_id)

    assert result.completeness == "complete"
    assert result.total_value == Money("10000.00")
    by_security = {line.security_id: line for line in result.holdings}
    security_line = by_security[security.id]
    assert security_line.units == Units("100")
    assert security_line.price == Price("100.00")
    assert security_line.market_value == Money("10000.00")
    assert security_line.target_weight_pct == Decimal("1.0000")
    assert security_line.drift_pct == Decimal("0.0000")
    assert security_line.is_flagged is False
    cash_line = by_security[None]
    assert cash_line.units is None
    assert cash_line.price is None


def test_partial_valuation_yields_no_entries(db_committing: Session) -> None:
    """A held security with no confirmed close (S4 §4) -- the whole evaluation is partial, and
    `holdings` is empty, never a silent "you hold nothing" (NFR-6)."""
    customer_id = _seed_customer(db_committing)
    security = Security(
        symbol="NOCLOSE", name="No Close Co.", asset_class=SecurityAssetClass.EQUITY
    )
    db_committing.add(security)
    db_committing.flush()
    # Deliberately no DailyClose row for `security`.
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
    )
    cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
    )
    db_committing.add_all([cash, equity, units, cost])
    db_committing.flush()

    posting = PostingService(_LedgerLikeUow(db_committing))
    posting.post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=MARKET_DATE,
        source_event_id=_insert_event(db_committing),
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-10000.00")),
        ],
    )
    posting.post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=MARKET_DATE,
        source_event_id=_insert_event(db_committing),
        legs=[
            PostingLeg(account_id=units.id, quantity_units=Units("100")),
            PostingLeg(account_id=cost.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=cash.id, amount_money=Money("-10000.00")),
        ],
    )

    model = ModelPortfolio(name="Test Model")
    db_committing.add(model)
    db_committing.flush()
    db_committing.add(
        TargetWeight(
            model_portfolio_id=model.id, security_id=security.id, weight_pct=Decimal("1.0000")
        )
    )
    db_committing.add(
        CustomerModelAssignment(
            customer_id=customer_id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
        )
    )
    db_committing.commit()

    result = _holdings(customer_id)

    assert result.completeness == "partial"
    assert result.holdings == ()
