"""`CorporateActionService` against real Postgres: dividend two-step and split (S5 §6, FR-23/24)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.models.identity.customer import Customer
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ledger.settlement_obligation import SettlementObligationStatus
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.marketdata.daily_close import DailyClose
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.models.restatement.restatement_event import RestatementEvent
from app.services.lots.corporate_action_service import CorporateActionService
from app.services.lots.uow import LotsUnitOfWork
from tests.integration.conftest import LEDGER_TABLES

CORPORATE_ACTION_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
    PublishedSnapshot.__table__,
    RestatementEvent.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
]


@pytest.fixture
def corporate_action_tables(owner_engine):
    for table in CORPORATE_ACTION_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(CORPORATE_ACTION_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("corporate_action_tables")


def _owner_uow() -> LotsUnitOfWork:
    return LotsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _insert_customer(uow: LotsUnitOfWork) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    uow.session.add(customer)
    uow.session.flush()
    uow.session.add(CustomerCashLock(customer_id=customer.id))
    uow.session.flush()
    return customer.id


def _insert_security(uow: LotsUnitOfWork, *, symbol: str = "AAPL") -> uuid.UUID:
    security = Security(symbol=symbol, name="Apple Inc.", asset_class=SecurityAssetClass.EQUITY)
    uow.session.add(security)
    uow.session.flush()
    return security.id


def _open_lot(
    uow: LotsUnitOfWork,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    quantity: Units,
    cost_basis: Money,
    execution_id: str | None = None,
) -> TaxLot:
    """Minimal order/order_event chain plus the lot, standing in for `LotConsumptionService`."""
    execution_id = execution_id or str(uuid.uuid4())
    order = Order(
        customer_id=customer_id,
        security_id=security_id,
        side=OrderSide.BUY,
        quantity_requested=quantity,
        status=OrderStatus.FILLED,
        filled_quantity=quantity,
        client_order_id=derive_client_order_id(uuid.uuid4()),
    )
    uow.session.add(order)
    uow.session.flush()
    uow.session.add(
        OrderEvent(
            order_id=order.id,
            seq=1,
            event_type=OrderEventType.FILL,
            execution_id=execution_id,
            payload={},
        )
    )
    uow.session.flush()
    lot = TaxLot(
        customer_id=customer_id,
        security_id=security_id,
        opening_fill_execution_id=execution_id,
        quantity_opened=quantity,
        quantity_remaining=quantity,
        original_cost_basis=cost_basis,
        adjusted_basis=cost_basis,
        acquired_at=date(2026, 1, 1),
        designation=LotDesignation.UNSPECIFIED,
        designation_window_closes_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    uow.session.add(lot)
    uow.session.flush()
    return lot


# --- declare_dividend_ex_date (S5 §6.1 step 1) ------------------------------------------------


def test_dividend_ex_date_posts_one_entry_per_holder_sized_at_per_share_times_quantity() -> None:
    from app.models.ledger.posting import Posting

    with _owner_uow() as uow:
        security_id = _insert_security(uow)
        customer_a = _insert_customer(uow)
        customer_b = _insert_customer(uow)
        _open_lot(
            uow, customer_id=customer_a, security_id=security_id,
            quantity=Units("200"), cost_basis=Money("2000.00"),
        )
        _open_lot(
            uow, customer_id=customer_b, security_id=security_id,
            quantity=Units("40"), cost_basis=Money("400.00"),
        )

        entries = CorporateActionService(uow).declare_dividend_ex_date(
            security_id=security_id, per_share_amount=Price("0.25"), ex_date=date(2026, 3, 1)
        )
        uow.commit()

        assert len(entries) == 2  # one entry per holder
        for entry in entries:
            assert entry.entry_type is JournalEntryType.DIVIDEND

        legs_by_entry = {
            entry.id: sorted(
                leg.amount_money
                for leg in uow.session.query(Posting).filter_by(journal_entry_id=entry.id).all()
            )
            for entry in entries
        }
        # 200 * 0.25 = 50.00; 40 * 0.25 = 10.00.
        assert sorted(legs_by_entry.values()) == [
            [Money("-50.00"), Money("50.00")],
            [Money("-10.00"), Money("10.00")],
        ]

        receivable_a = uow.session.query(Account).filter_by(
            customer_id=customer_a, role=AccountRole.DIVIDEND_RECEIVABLE
        ).one()
        assert receivable_a is not None


def test_dividend_ex_date_skips_a_customer_with_zero_remaining_quantity() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("100"), cost_basis=Money("1000.00"),
        )
        lot.quantity_remaining = Units("0")  # fully sold before ex-date
        uow.session.flush()

        entries = CorporateActionService(uow).declare_dividend_ex_date(
            security_id=security_id, per_share_amount=Price("0.50"), ex_date=date(2026, 3, 1)
        )
        uow.commit()

        assert entries == []


# --- pay_dividend (S5 §6.1 step 2) -------------------------------------------------------------


def test_pay_dividend_debits_cash_credits_receivable_and_opens_a_pending_obligation() -> None:
    from app.models.ledger.posting import Posting
    from app.models.ledger.settlement_obligation import SettlementObligation

    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        # pay_dividend requires an existing cash account.
        uow.session.add(Account.create(AccountRole.CASH, customer_id=customer_id))
        uow.session.flush()
        _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("100"), cost_basis=Money("1000.00"),
        )
        CorporateActionService(uow).declare_dividend_ex_date(
            security_id=security_id, per_share_amount=Price("0.50"), ex_date=date(2026, 3, 1)
        )

        entry = CorporateActionService(uow).pay_dividend(
            customer_id=customer_id, amount=Money("50.00"), pay_date=date(2026, 3, 10)
        )
        uow.commit()

        assert entry.entry_type is JournalEntryType.DIVIDEND
        legs = sorted(
            leg.amount_money
            for leg in uow.session.query(Posting).filter_by(journal_entry_id=entry.id).all()
        )
        assert legs == [Money("-50.00"), Money("50.00")]  # cash +50, receivable -50

        obligation = (
            uow.session.query(SettlementObligation).filter_by(journal_entry_id=entry.id).one()
        )
        assert obligation.status is SettlementObligationStatus.PENDING
        assert obligation.amount_money == Money("50.00")
        assert obligation.expected_settlement_date == date(2026, 3, 10)


# --- apply_split (S5 §6.2, FR-24) ---------------------------------------------------------------


def test_split_doubles_quantities_and_preserves_basis() -> None:
    """Quantities double on a 2-for-1; basis is untouched since value must not move (FR-24)."""
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("100"), cost_basis=Money("1500.00"),
        )
        lot_id = lot.id

        entries = CorporateActionService(uow).apply_split(
            security_id=security_id, ratio=2, effective_date=date(2026, 4, 1)
        )
        uow.commit()

    with _owner_uow() as uow:
        refreshed = uow.session.get(TaxLot, lot_id)
        assert refreshed.quantity_opened == Units("200")
        assert refreshed.quantity_remaining == Units("200")
        assert refreshed.original_cost_basis == Money("1500.00")  # unchanged -- FR-24
        assert refreshed.adjusted_basis == Money("1500.00")  # unchanged -- FR-24

        assert len(entries) == 1
        assert entries[0].entry_type is JournalEntryType.SPLIT
        from app.models.ledger.posting import Posting

        legs = uow.session.query(Posting).filter_by(journal_entry_id=entries[0].id).all()
        assert len(legs) == 1
        assert legs[0].amount_money is None  # units-only entry, no money legs (FR-24)
        assert legs[0].quantity_units == Units("100")  # added_units = prior_total * (ratio - 1)


def test_split_skips_a_security_with_no_open_lots() -> None:
    with _owner_uow() as uow:
        security_id = _insert_security(uow)

        entries = CorporateActionService(uow).apply_split(
            security_id=security_id, ratio=2, effective_date=date(2026, 4, 1)
        )
        uow.commit()

        assert entries == []


@pytest.mark.parametrize("ratio", [1, 0, -1])
def test_split_rejects_a_ratio_not_greater_than_one(ratio: int) -> None:
    with _owner_uow() as uow:
        security_id = _insert_security(uow)
        with pytest.raises(ValueError, match="ratio"):
            CorporateActionService(uow).apply_split(
                security_id=security_id, ratio=ratio, effective_date=date(2026, 4, 1)
            )
