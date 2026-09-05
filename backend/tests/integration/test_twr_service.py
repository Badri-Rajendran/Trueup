"""`TwrService.compute_twr` (S4 §5, ADR 3) — sub-period breaks, FR-17's flow-timing invariance,
and the restatement-composability property (S4 §5/§9: a corrected close touches exactly one
stored sub-period row).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
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
from app.services.valuation.twr_service import TwrService
from app.services.valuation.uow import ValuationUnitOfWork
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


def _valuation_uow(session, *, customer_id: uuid.UUID) -> ValuationUnitOfWork:
    return ValuationUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, session_factory=lambda: session
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


def _post_flow(
    session, accounts, *, entry_type: JournalEntryType, amount: Money, effective_date: date
) -> None:
    event_id = insert_inbound_event(session)
    signed = amount if entry_type is JournalEntryType.DEPOSIT else -amount
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=entry_type,
        effective_date=effective_date,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=accounts["cash"].id, amount_money=signed),
            PostingLeg(account_id=accounts["customer_equity"].id, amount_money=-signed),
        ],
    )


def _post_buy(session, accounts, *, units: Units, cost: Money, effective_date: date) -> None:
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


def _close(session, *, security_id: uuid.UUID, market_date: date, price: Price) -> None:
    session.add(
        DailyClose(
            security_id=security_id,
            market_date=market_date,
            close_price=price,
            source=MarketDataSource.LIVE,
            status=DailyCloseStatus.CONFIRMED,
            recorded_at=datetime.now(UTC),
        )
    )
    session.flush()


def test_zero_positions_and_no_flows_is_zero_percent(db_committing) -> None:
    """S4 §8 case 1."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()

    assert result.twr == Decimal("0")
    assert result.is_provisional is False


def test_first_sub_period_return_is_zero_by_construction(db_committing) -> None:
    """S4 §8 case 3: `v_begin` is the deposit that opened the account -- `value_book(v_begin)`
    already reflects it, so the first sub-period's return is zero even though money moved."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("5000.00"),
        effective_date=date(2026, 9, 1),
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 1))
        uow.commit()

    assert result.twr == Decimal("0")


def test_two_same_day_flows_produce_one_sub_period_break_not_two(db_committing) -> None:
    """S4 §8 case 2."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("200.00"),
        effective_date=date(2026, 9, 5),
    )
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.WITHDRAWAL,
        amount=Money("50.00"),
        effective_date=date(2026, 9, 5),
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()

    # 3 boundaries (start, 2026-09-05, end) -> exactly 2 sub-periods, not 3.
    assert len(result.sub_periods) == 2
    assert result.twr == Decimal("0")


def test_a_deposit_mid_period_does_not_pollute_the_return(db_committing) -> None:
    """FR-17: the market grows from $1000 to $1100 (10%) in the first sub-period, then a $500
    deposit lands, then the market is flat -- the linked TWR must be 10%, not diluted or inflated
    by the deposit itself."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 1), price=Price("100.00")
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 5), price=Price("110.00")
    )
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("500.00"),
        effective_date=date(2026, 9, 5),
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 10), price=Price("110.00")
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()

    assert len(result.sub_periods) == 2
    assert result.sub_periods[0].return_pct == Decimal("0.1000000000")
    assert result.sub_periods[1].return_pct == Decimal("0")
    assert result.twr == Decimal("0.1000000000")


def test_partial_valuation_flags_the_sub_period_provisional(db_committing) -> None:
    """S4 §8 case 4: a sub-period whose `v_end` lands on a day with no confirmed close is
    provisional, not silently treated as complete."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 1), price=Price("100.00")
    )
    # No close for 2026-09-10 -- the period's end lands on a missing valuation.
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()

    assert result.is_provisional is True
    assert result.sub_periods[0].is_provisional is True


def test_a_corrected_close_re_links_only_the_affected_sub_period(db_committing) -> None:
    """S4 §5/§9: a corrected close for one day re-links exactly that sub-period; every other
    stored `sub_period_return` row is byte-for-byte unchanged (same id, same recorded_at)."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = _security(db_committing)
    accounts = _accounts(db_committing, customer_id, security.id)
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _post_buy(
        db_committing,
        accounts,
        units=Units("10.000000"),
        cost=Money("1000.00"),
        effective_date=date(2026, 9, 1),
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 1), price=Price("100.00")
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 5), price=Price("110.00")
    )
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("500.00"),
        effective_date=date(2026, 9, 5),
    )
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 10), price=Price("120.00")
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        first = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()
    assert len(first.sub_periods) == 2
    first_sub_period = (first.sub_periods[0].id, first.sub_periods[0].recorded_at)
    second_sub_period = (first.sub_periods[1].id, first.sub_periods[1].recorded_at)

    # A correction to the *second* sub-period's closing price only (2026-09-10), recorded later.
    _close(
        db_committing, security_id=security.id, market_date=date(2026, 9, 10), price=Price("130.00")
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        second = TwrService(uow).compute_twr(customer_id, date(2026, 9, 1), date(2026, 9, 10))
        uow.commit()

    assert (second.sub_periods[0].id, second.sub_periods[0].recorded_at) == first_sub_period
    assert second.sub_periods[0].return_pct == first.sub_periods[0].return_pct
    assert (second.sub_periods[1].id, second.sub_periods[1].recorded_at) != second_sub_period
    assert second.sub_periods[1].return_pct != first.sub_periods[1].return_pct
    assert second.twr != first.twr

    # Exactly one row exists for the unaffected sub-period -- the correction never wrote a
    # second one, matching "left untouched" literally, not just "recomputed to the same value".
    unaffected_rows = (
        db_committing.query(SubPeriodReturn)
        .filter_by(
            customer_id=customer_id,
            sub_period_start=first.sub_periods[0].sub_period_start,
            sub_period_end=first.sub_periods[0].sub_period_end,
        )
        .all()
    )
    assert len(unaffected_rows) == 1


@settings(
    max_examples=15,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(flow_offset_days=st.integers(min_value=1, max_value=8))
def test_twr_is_unaffected_by_flow_timing(db_committing, flow_offset_days: int) -> None:
    """FR-17, property-based: a cash-only account (no market exposure) has an exact 0% TWR no
    matter which day within the period an external flow lands."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
    }
    db_committing.add_all(accounts.values())
    db_committing.flush()

    period_start = date(2026, 9, 1)
    period_end = date(2026, 9, 10)
    flow_date = period_start + timedelta(days=flow_offset_days)

    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.DEPOSIT,
        amount=Money("2000.00"),
        effective_date=period_start,
    )
    _post_flow(
        db_committing,
        accounts,
        entry_type=JournalEntryType.WITHDRAWAL,
        amount=Money("300.00"),
        effective_date=flow_date,
    )
    db_committing.commit()

    with _valuation_uow(db_committing, customer_id=customer_id) as uow:
        result = TwrService(uow).compute_twr(customer_id, period_start, period_end)
        uow.commit()

    assert result.twr == Decimal("0")
