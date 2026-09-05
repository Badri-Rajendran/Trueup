"""`DailyValuationJob` (S4 foundation surface map, §3.2/§6) — the calendar-then-closes-then-
completeness pipeline, against real Postgres.

The outer `JobRun`-tracking `UnitOfWork` is faked here (its own lock/outcome behaviour is already
covered generically by `tests/unit/test_jobs.py`'s `NoopJob` tests); the job's real
`work_uow_factory` default is used for its own domain writes, over the `DbRole.WORKER` engine --
a separate connection from `db_committing`'s, committed for real and then read back through
`db_committing` (same database, both real Postgres connections)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.money import Money, Price
from app.core.money import Units as UnitsValue
from app.integrations.fake.fake_calendar import FakeCalendarAdapter
from app.integrations.fake.fake_market_data import FakeMarketDataAdapter
from app.integrations.ports import CloseQuote, TradingDayInfo
from app.jobs.base import JobOutcome
from app.jobs.daily_valuation import DailyValuationJob
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun, ValuationRunStatus
from app.services.ledger.posting_service import PostingLeg, PostingService
from tests.integration.conftest import LEDGER_TABLES, insert_customer, insert_inbound_event

MARKETDATA_TABLES = [
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
]


@pytest.fixture
def valuation_tables(owner_engine):
    for table in LEDGER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    for table in MARKETDATA_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(MARKETDATA_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))


pytestmark = pytest.mark.usefixtures("valuation_tables")


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


class _FakeJobRuns:
    def add_run(self, run: object) -> None:
        return None


class _FakeOuterUow:
    """Stands in for the `JobRun`-tracking `UnitOfWork` (module docstring)."""

    def __init__(self) -> None:
        self.job_runs = _FakeJobRuns()

    def __enter__(self) -> _FakeOuterUow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def try_advisory_lock(self, job_name: str) -> bool:
        return True

    def release_advisory_lock(self, job_name: str) -> None:
        return None

    def commit(self) -> None:
        return None


def _open_position(session, *, symbol: str = "AAPL") -> Security:
    security = Security(symbol=symbol, name="Test Co.", asset_class=SecurityAssetClass.EQUITY)
    session.add(security)
    session.flush()

    customer_id = insert_customer(session)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
    )
    cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
    )
    session.add_all([cash, equity, units, cost])
    session.flush()

    event_id = insert_inbound_event(session)
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=cash.id, amount_money=Money("1000.00")),
            PostingLeg(account_id=equity.id, amount_money=Money("-1000.00")),
        ],
    )
    event_id = insert_inbound_event(session)
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=date(2026, 9, 1),
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=units.id, quantity_units=UnitsValue("10.000000")),
            PostingLeg(account_id=cost.id, amount_money=Money("1000.00")),
            PostingLeg(account_id=cash.id, amount_money=Money("-1000.00")),
        ],
    )
    return security


def test_a_trading_day_with_a_confirmed_close_is_a_complete_valuation_run(db_committing) -> None:
    security = _open_position(db_committing)
    db_committing.commit()

    market_date = date(2026, 9, 2)
    calendar_port = FakeCalendarAdapter()
    calendar_port.set_trading_day(
        TradingDayInfo(
            market_date=market_date,
            is_trading_day=True,
            session_open_at=datetime(2026, 9, 2, 13, 30, tzinfo=UTC),
            session_close_at=datetime(2026, 9, 2, 20, 0, tzinfo=UTC),
        )
    )
    market_data_port = FakeMarketDataAdapter()
    market_data_port.set_close(
        CloseQuote(
            security_symbol=security.symbol, market_date=market_date, close_price=Price("105.00")
        )
    )

    job = DailyValuationJob(
        market_data_port=market_data_port,
        calendar_port=calendar_port,
        uow_factory=_FakeOuterUow,
    )

    outcome = job.run(market_date=market_date)

    assert outcome is JobOutcome.COMPLETED
    calendar_row = db_committing.query(MarketCalendarCache).filter_by(market_date=market_date).one()
    assert calendar_row.is_trading_day is True

    close_row = (
        db_committing.query(DailyClose)
        .filter_by(security_id=security.id, market_date=market_date)
        .one()
    )
    assert close_row.status is DailyCloseStatus.CONFIRMED
    assert close_row.close_price == Price("105.00")
    assert close_row.source is MarketDataSource.LIVE

    run_row = db_committing.query(ValuationRun).filter_by(market_date=market_date).one()
    assert run_row.status is ValuationRunStatus.COMPLETE
    assert run_row.securities_expected == 1
    assert run_row.securities_confirmed == 1


def test_a_missing_close_on_a_trading_day_is_a_partial_valuation_run(db_committing) -> None:
    security = _open_position(db_committing)
    db_committing.commit()

    market_date = date(2026, 9, 2)
    calendar_port = FakeCalendarAdapter()
    calendar_port.set_trading_day(
        TradingDayInfo(
            market_date=market_date,
            is_trading_day=True,
            session_open_at=datetime(2026, 9, 2, 13, 30, tzinfo=UTC),
            session_close_at=datetime(2026, 9, 2, 20, 0, tzinfo=UTC),
        )
    )
    market_data_port = FakeMarketDataAdapter()  # no close seeded -- provider has nothing yet

    job = DailyValuationJob(
        market_data_port=market_data_port,
        calendar_port=calendar_port,
        uow_factory=_FakeOuterUow,
    )

    job.run(market_date=market_date)

    assert (
        db_committing.query(DailyClose)
        .filter_by(security_id=security.id, market_date=market_date)
        .first()
        is None
    )  # S4 §6: missing is inferred by absence, never a stored row.

    run_row = db_committing.query(ValuationRun).filter_by(market_date=market_date).one()
    assert run_row.status is ValuationRunStatus.PARTIAL
    assert run_row.securities_expected == 1
    assert run_row.securities_confirmed == 0


def test_a_holiday_writes_the_calendar_cache_but_no_valuation_run(db_committing) -> None:
    """S4 §6: a non-trading day is never expected to have a valuation_run row at all."""
    _open_position(db_committing)
    db_committing.commit()

    market_date = date(2026, 1, 1)
    calendar_port = FakeCalendarAdapter()
    calendar_port.set_trading_day(
        TradingDayInfo(
            market_date=market_date,
            is_trading_day=False,
            session_open_at=None,
            session_close_at=None,
        )
    )
    market_data_port = FakeMarketDataAdapter()

    job = DailyValuationJob(
        market_data_port=market_data_port,
        calendar_port=calendar_port,
        uow_factory=_FakeOuterUow,
    )

    job.run(market_date=market_date)

    calendar_row = db_committing.query(MarketCalendarCache).filter_by(market_date=market_date).one()
    assert calendar_row.is_trading_day is False
    assert db_committing.query(ValuationRun).filter_by(market_date=market_date).first() is None
