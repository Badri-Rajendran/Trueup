"""`ValuationService.value_book` against real Postgres: `NUMERIC` rounding and `recorded_at`
bitemporal ordering (S4 §4/§8 cases 1/5/§9)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.valuation.uow import ValuationUnitOfWork
from app.services.valuation.valuation_service import ValuationService
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
    # Raw DROP TABLE, not Table.drop(): a shared Postgres enum makes per-Table drop events race.
    with owner_engine.begin() as connection:
        for table in reversed(MARKETDATA_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))


pytestmark = pytest.mark.usefixtures("valuation_tables")


class _LedgerLikeUow:
    """`PostingService`'s minimal dependency."""

    def __init__(self, session):
        self.session = session

        class _Repo:
            def __init__(self, session):
                self._session = session

            def add(self, obj):
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


def _valuation_uow(session, *, customer_id: uuid.UUID | None = None) -> ValuationUnitOfWork:
    role = SessionRole.CUSTOMER if customer_id is not None else SessionRole.ADMIN
    return ValuationUnitOfWork(
        customer_id=customer_id, role=role, session_factory=lambda: session
    )


def _accounts(session, customer_id: uuid.UUID, security_id: uuid.UUID) -> dict[str, Account]:
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
        "position_units": Account.create(
            AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security_id
        ),
        "position_cost": Account.create(
            AccountRole.POSITION_COST, customer_id=customer_id, security_id=security_id
        ),
    }
    session.add_all(accounts.values())
    session.flush()
    return accounts


def _post_deposit(session, accounts, *, amount: Money, effective_date: date) -> None:
    event_id = insert_inbound_event(session)
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=effective_date,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["cash"].id, amount_money=amount),
            PostingLeg(account_id=accounts["customer_equity"].id, amount_money=-amount),
        ],
    )


def _post_buy(
    session,
    accounts,
    *,
    units: Units,
    cost: Money,
    effective_date: date,
) -> None:
    event_id = insert_inbound_event(session)
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=effective_date,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["position_units"].id, quantity_units=units),
            PostingLeg(account_id=accounts["position_cost"].id, amount_money=cost),
            PostingLeg(account_id=accounts["cash"].id, amount_money=-cost),
        ],
    )


def _security(session, *, symbol: str = "AAPL") -> Security:
    security = Security(symbol=symbol, name="Apple Inc.", asset_class=SecurityAssetClass.EQUITY)
    session.add(security)
    session.flush()
    return security


def _close(
    session,
    *,
    security_id: uuid.UUID,
    market_date: date,
    price: Price,
    status: DailyCloseStatus = DailyCloseStatus.CONFIRMED,
    recorded_at: datetime | None = None,
) -> DailyClose:
    close = DailyClose(
        security_id=security_id,
        market_date=market_date,
        close_price=price,
        source=MarketDataSource.LIVE,
        status=status,
        recorded_at=recorded_at or datetime.now(UTC),
    )
    session.add(close)
    session.flush()
    return close


def test_zero_positions_values_the_cash_balance_alone(db_committing) -> None:
    """S4 §8 case 1: fully in cash -- value_book returns the cash balance alone."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_deposit(db_committing, accounts, amount=Money("1000.00"), effective_date=date(2026, 9, 1))
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = ValuationService(uow).value_book(customer_id, date(2026, 9, 1))

    assert result.total_value == Money("1000.00")
    assert result.completeness == "complete"
    assert result.as_of_date == date(2026, 9, 1)


def test_confirmed_close_prices_the_position_with_exact_numeric_rounding(db_committing) -> None:
    """S4 §4/§9: `Price * Units -> Money` against real NUMERIC columns (ADR 16)."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_deposit(
        db_committing, accounts, amount=Money("10000.00"), effective_date=date(2026, 9, 1)
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("3.333333"),
        cost=Money("500.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing,
        security_id=security.id,
        market_date=date(2026, 9, 2),
        price=Price("150.005"),
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = ValuationService(uow).value_book(customer_id, date(2026, 9, 2))

    expected_position_value = Units("3.333333") * Price("150.005")
    expected_cash = Money("9500.00")
    assert result.total_value == expected_cash + expected_position_value
    assert result.completeness == "complete"


def test_missing_close_flags_partial_and_omits_the_position(db_committing) -> None:
    """S4 §6: no close at all -- inferred by absence, whole book flagged partial."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_deposit(
        db_committing, accounts, amount=Money("10000.00"), effective_date=date(2026, 9, 1)
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    db_committing.commit()
    # No daily_close row at all for 2026-09-02.

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = ValuationService(uow).value_book(customer_id, date(2026, 9, 2))

    assert result.total_value == Money("9000.00")  # cash only; position omitted, not zeroed-in
    assert result.completeness == "partial"


def test_stale_only_close_is_treated_the_same_as_missing(db_committing) -> None:
    """S4 §6: a `stale`-flagged close never substitutes for a confirmed one."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_deposit(
        db_committing, accounts, amount=Money("10000.00"), effective_date=date(2026, 9, 1)
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing,
        security_id=security.id,
        market_date=date(2026, 9, 2),
        price=Price("100.00"),
        status=DailyCloseStatus.STALE,
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = ValuationService(uow).value_book(customer_id, date(2026, 9, 2))

    assert result.total_value == Money("9000.00")
    assert result.completeness == "partial"


def test_a_later_recorded_at_correction_wins_however_many_followed(db_committing) -> None:
    """S4 §8 case 5: `value_book` always reads the latest `recorded_at`'s confirmed row."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_deposit(
        db_committing, accounts, amount=Money("10000.00"), effective_date=date(2026, 9, 1)
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing,
        security_id=security.id,
        market_date=date(2026, 9, 2),
        price=Price("100.00"),
        recorded_at=datetime(2026, 9, 2, 16, 5, tzinfo=UTC),
    )
    _close(
        db_committing,
        security_id=security.id,
        market_date=date(2026, 9, 2),
        price=Price("101.50"),
        recorded_at=datetime(2026, 9, 2, 18, 0, tzinfo=UTC),
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = ValuationService(uow).value_book(customer_id, date(2026, 9, 2))

    assert result.total_value == Money("9000.00") + Units("10.000000") * Price("101.50")
    assert result.completeness == "complete"
