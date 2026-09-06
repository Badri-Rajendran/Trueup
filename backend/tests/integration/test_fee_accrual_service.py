"""`FeeAccrualService`/`HighWaterMarkService` against real Postgres: deposit-vs-gain property,
same-transaction accrual/HWM guarantee, and accrual idempotency (S10 §4/§8/§9)."""

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
from app.models.fees.fee_accrual import FeeAccrual
from app.models.fees.high_water_mark import HighWaterMark
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.services.fees.fee_accrual_service import FeeAccrualService
from app.services.fees.uow import FeesUnitOfWork
from app.services.ledger.posting_service import PostingLeg, PostingService
from tests.integration.conftest import LEDGER_TABLES, insert_customer, insert_inbound_event

FEES_TABLES = [
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
    HighWaterMark.__table__,
    FeeAccrual.__table__,
]


@pytest.fixture
def fees_tables(owner_engine):
    for table in LEDGER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    for table in FEES_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(FEES_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))
        for table in reversed(LEDGER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("fees_tables")


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


def _cash_accounts(session, customer_id: uuid.UUID) -> dict[str, Account]:
    accounts = {
        "cash": Account.create(AccountRole.CASH, customer_id=customer_id),
        "customer_equity": Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id),
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


# --- S10 §8 edge case 2: the deposit-vs-gain property (the most important test in this wave) -----


@settings(
    max_examples=15, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    deposit_amounts=st.lists(
        st.decimals(min_value="1.00", max_value="5000.00", places=2), min_size=1, max_size=4
    )
)
def test_pure_deposits_with_zero_market_movement_accrue_exactly_zero_fee(
    db_committing, deposit_amounts: list[Decimal]
) -> None:
    """A cash-only account receiving only deposits accrues exactly zero fee under a nonzero
    rate (S10 §8 edge case 2)."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    accounts = _cash_accounts(db_committing, customer_id)

    day = date(2026, 9, 1)
    for amount in deposit_amounts:
        _post_flow(
            db_committing,
            accounts,
            entry_type=JournalEntryType.DEPOSIT,
            amount=Money(str(amount)),
            effective_date=day,
        )
        day += timedelta(days=1)
    db_committing.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        service = FeeAccrualService(uow, fee_rate_pct=Decimal("0.20"))  # deliberately nonzero
        check_date = date(2026, 9, 1)
        last_day = day + timedelta(days=3)  # a few days past the last deposit
        while check_date <= last_day:
            accrual = service.accrue_for_customer(customer_id, check_date)
            if accrual is not None:
                assert accrual.gain_amount == Money("0.00")
                assert accrual.fee_amount == Money("0.00")
            check_date += timedelta(days=1)
        uow.commit()


def test_genuine_market_gain_above_the_peak_accrues_a_real_fee(db_committing) -> None:
    """Mirror check: a real gain above the prior peak accrues a nonzero fee."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = Security(symbol="AAPL", name="Apple Inc.", asset_class=SecurityAssetClass.EQUITY)
    db_committing.add(security)
    db_committing.flush()
    accounts = _cash_accounts(db_committing, customer_id)
    position_units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
    )
    position_cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
    )
    db_committing.add_all([position_units, position_cost])
    db_committing.flush()

    day1, day2 = date(2026, 9, 1), date(2026, 9, 2)
    _post_flow(
        db_committing, accounts, entry_type=JournalEntryType.DEPOSIT,
        amount=Money("10000.00"), effective_date=day1,
    )
    event_id = insert_inbound_event(db_committing)
    PostingService(_LedgerLikeUow(db_committing)).post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=day1,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=position_units.id, quantity_units=Units("100")),
            PostingLeg(account_id=position_cost.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=accounts["cash"].id, amount_money=Money("-10000.00")),
        ],
    )
    db_committing.add(
        DailyClose(
            security_id=security.id, market_date=day1, close_price=Price("100.00"),
            source=MarketDataSource.LIVE, status=DailyCloseStatus.CONFIRMED,
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.add(
        DailyClose(
            security_id=security.id, market_date=day2, close_price=Price("110.00"),
            source=MarketDataSource.LIVE, status=DailyCloseStatus.CONFIRMED,
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        service = FeeAccrualService(uow, fee_rate_pct=Decimal("0.20"))
        service.accrue_for_customer(customer_id, day1)  # first-ever day: HWM initializes, zero gain
        accrual = service.accrue_for_customer(customer_id, day2)
        uow.commit()

    assert accrual is not None
    assert accrual.gain_amount == Money("1000.00")  # 100 units * ($110 - $100)
    assert accrual.fee_amount > Money("0.00")


# --- Same-transaction guarantee (S9's own hold-release pattern, applied here) ---------------------


def test_killing_the_transaction_midway_persists_neither_the_accrual_nor_the_hwm_update(
    db_committing, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S10 §4/§9: HWM ratchet and fee_accrual insert share one SAVEPOINT and roll back together."""
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    security = Security(symbol="AAPL", name="Apple Inc.", asset_class=SecurityAssetClass.EQUITY)
    db_committing.add(security)
    db_committing.flush()
    accounts = _cash_accounts(db_committing, customer_id)
    position_units = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
    )
    position_cost = Account.create(
        AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
    )
    db_committing.add_all([position_units, position_cost])
    db_committing.flush()

    day1, day2 = date(2026, 9, 1), date(2026, 9, 2)
    _post_flow(
        db_committing, accounts, entry_type=JournalEntryType.DEPOSIT,
        amount=Money("10000.00"), effective_date=day1,
    )
    event_id = insert_inbound_event(db_committing)
    PostingService(_LedgerLikeUow(db_committing)).post(
        entry_type=JournalEntryType.TRADE_BUY,
        effective_date=day1,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=position_units.id, quantity_units=Units("100")),
            PostingLeg(account_id=position_cost.id, amount_money=Money("10000.00")),
            PostingLeg(account_id=accounts["cash"].id, amount_money=Money("-10000.00")),
        ],
    )
    # $100 -> $110/share so day 2's shadow-NAV exceeds day 1's peak.
    db_committing.add(
        DailyClose(
            security_id=security.id, market_date=day1, close_price=Price("100.00"),
            source=MarketDataSource.LIVE, status=DailyCloseStatus.CONFIRMED,
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.add(
        DailyClose(
            security_id=security.id, market_date=day2, close_price=Price("110.00"),
            source=MarketDataSource.LIVE, status=DailyCloseStatus.CONFIRMED,
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        service = FeeAccrualService(uow, fee_rate_pct=Decimal("0.20"))
        service.accrue_for_customer(customer_id, day1)  # HWM initializes at 10000.00, zero gain
        uow.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        peak_before = uow.high_water_marks.get_by_customer(customer_id).peak_value
    assert peak_before == Money("10000.00")

    class _SimulatedPostingFailureError(Exception):
        pass

    def _raise(*args: object, **kwargs: object) -> None:
        raise _SimulatedPostingFailureError

    monkeypatch.setattr(
        "app.services.fees.fee_accrual_service.PostingService.post", _raise
    )

    with pytest.raises(_SimulatedPostingFailureError), _fees_uow(
        db_committing, customer_id=customer_id
    ) as uow:
        service = FeeAccrualService(uow, fee_rate_pct=Decimal("0.20"))
        service.accrue_for_customer(customer_id, day2)
        uow.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        hwm = uow.high_water_marks.get_by_customer(customer_id)
        accruals = (
            uow.session.query(FeeAccrual)
            .filter_by(customer_id=customer_id, accrual_date=day2)
            .all()
        )
        assert hwm is not None
        assert hwm.peak_value == Money("10000.00")  # unchanged -- ratchet rolled back
        assert accruals == []  # insert never landed


# --- S10 §8 edge case 4: job-level idempotency ----------------------------------------------------


def test_a_second_full_accrual_for_an_already_accrued_date_is_a_clean_no_op(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    db_committing.add(CustomerCashLock(customer_id=customer_id))
    accounts = _cash_accounts(db_committing, customer_id)
    _post_flow(
        db_committing, accounts, entry_type=JournalEntryType.DEPOSIT,
        amount=Money("10000.00"), effective_date=date(2026, 9, 1),
    )
    db_committing.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        FeeAccrualService(uow, fee_rate_pct=Decimal("0.20")).accrue_for_customer(
            customer_id, date(2026, 9, 1)
        )
        uow.commit()

    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        result = FeeAccrualService(uow, fee_rate_pct=Decimal("0.20")).accrue_for_customer(
            customer_id, date(2026, 9, 1)
        )
        uow.commit()

    assert result is None
    with _fees_uow(db_committing, customer_id=customer_id) as uow:
        rows = (
            uow.session.query(FeeAccrual)
            .filter_by(customer_id=customer_id, accrual_date=date(2026, 9, 1))
            .all()
        )
        assert len(rows) == 1  # never duplicated
