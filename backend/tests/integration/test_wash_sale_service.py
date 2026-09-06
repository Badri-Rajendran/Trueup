"""`WashSaleService` against real Postgres: the reactive check and disallowed-amount arithmetic
including the `min(loss, replacement_basis)` cap (S5 §5/§8, ADR 11)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.models.identity.customer import Customer
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.daily_close import DailyClose
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.models.restatement.restatement_event import RestatementEvent
from app.services.lots.uow import LotsUnitOfWork
from app.services.lots.wash_sale_service import WashSaleService
from tests.integration.conftest import LEDGER_TABLES

WASH_SALE_TABLES = [
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
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
]


@pytest.fixture
def wash_sale_tables(owner_engine):
    for table in WASH_SALE_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(WASH_SALE_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("wash_sale_tables")


def _owner_uow() -> LotsUnitOfWork:
    return LotsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _insert_customer(uow: LotsUnitOfWork) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    uow.session.add(customer)
    uow.session.flush()
    uow.session.add(CustomerCashLock(customer_id=customer.id))
    uow.session.flush()
    return customer.id


def _insert_security(uow: LotsUnitOfWork) -> uuid.UUID:
    security = Security(symbol="AAPL", name="Apple Inc.", asset_class=SecurityAssetClass.EQUITY)
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
    acquired_at: date,
) -> TaxLot:
    execution_id = str(uuid.uuid4())
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
            order_id=order.id, seq=1, event_type=OrderEventType.FILL,
            execution_id=execution_id, payload={},
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
        acquired_at=acquired_at,
        designation=LotDesignation.UNSPECIFIED,
        designation_window_closes_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    uow.session.add(lot)
    uow.session.flush()
    return lot


def _consume(
    uow: LotsUnitOfWork, *, tax_lot: TaxLot, realized_gain_loss: Money, sale_date: date
) -> LotConsumption:
    execution_id = str(uuid.uuid4())
    order = Order(
        customer_id=tax_lot.customer_id,
        security_id=tax_lot.security_id,
        side=OrderSide.SELL,
        quantity_requested=tax_lot.quantity_remaining,
        status=OrderStatus.FILLED,
        filled_quantity=tax_lot.quantity_remaining,
        client_order_id=derive_client_order_id(uuid.uuid4()),
    )
    uow.session.add(order)
    uow.session.flush()
    uow.session.add(
        OrderEvent(
            order_id=order.id, seq=1, event_type=OrderEventType.FILL,
            execution_id=execution_id, payload={},
        )
    )
    uow.session.flush()
    consumption = LotConsumption(
        closing_fill_execution_id=execution_id,
        tax_lot_id=tax_lot.id,
        quantity_consumed=tax_lot.quantity_remaining,
        realized_gain_loss=realized_gain_loss,
        is_provisional=False,
        sale_date=sale_date,
    )
    uow.session.add(consumption)
    uow.session.flush()
    return consumption


# --- on_loss_sale (trailing window) -------------------------------------------------------------


def test_on_loss_sale_is_a_no_op_for_a_gain() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=lot, realized_gain_loss=Money("50.00"), sale_date=date(2026, 2, 1)
        )

        WashSaleService(uow).on_loss_sale(
            consumption, customer_id=customer_id, security_id=security_id
        )
        uow.commit()

        assert (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one_or_none()
        ) is None


def test_on_loss_sale_is_a_no_op_with_no_replacement_in_window() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=lot, realized_gain_loss=Money("-50.00"), sale_date=date(2026, 2, 1)
        )
        # No other lot exists in the +/-30-day window.

        WashSaleService(uow).on_loss_sale(
            consumption, customer_id=customer_id, security_id=security_id
        )
        uow.commit()

        assert (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one_or_none()
        ) is None


def test_on_loss_sale_disallows_the_full_loss_when_replacement_basis_is_larger() -> None:
    """min(loss, replacement_basis): the loss is the binding constraint here."""
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        original_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=original_lot, realized_gain_loss=Money("-100.00"),
            sale_date=date(2026, 2, 1)
        )
        # Replacement bought within the trailing 30-day window; basis (2000) > loss (100).
        replacement_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("2000.00"), acquired_at=date(2026, 1, 22),
        )

        WashSaleService(uow).on_loss_sale(
            consumption, customer_id=customer_id, security_id=security_id
        )
        uow.commit()

        adjustment = (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one()
        )
        assert adjustment.disallowed_amount == Money("100.00")  # min(100, 2000) = 100
        assert adjustment.replacement_tax_lot_id == replacement_lot.id

        uow.session.refresh(consumption)
        uow.session.refresh(replacement_lot)
        assert consumption.realized_gain_loss == Money("0.00")  # -100 + 100 disallowed
        assert replacement_lot.adjusted_basis == Money("2100.00")  # 2000 + 100 carried in


def test_on_loss_sale_caps_disallowance_at_the_smaller_replacement_basis() -> None:
    """min(loss, replacement_basis): the replacement's basis is the binding constraint."""
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        original_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=original_lot, realized_gain_loss=Money("-500.00"),
            sale_date=date(2026, 2, 1)
        )
        # Replacement's basis (30) is smaller than the loss (500); the cap must bind.
        _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("1"), cost_basis=Money("30.00"), acquired_at=date(2026, 1, 22),
        )

        WashSaleService(uow).on_loss_sale(
            consumption, customer_id=customer_id, security_id=security_id
        )
        uow.commit()

        adjustment = (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one()
        )
        assert adjustment.disallowed_amount == Money("30.00")  # min(500, 30) = 30, the cap binds

        uow.session.refresh(consumption)
        assert consumption.realized_gain_loss == Money("-470.00")  # -500 + 30 disallowed


def test_on_loss_sale_is_idempotent_once_already_adjusted() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        original_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=original_lot, realized_gain_loss=Money("-100.00"),
            sale_date=date(2026, 2, 1)
        )
        _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("2000.00"), acquired_at=date(2026, 1, 22),
        )

        service = WashSaleService(uow)
        service.on_loss_sale(consumption, customer_id=customer_id, security_id=security_id)
        # A second call for the same consumption must not error or double-adjust.
        service.on_loss_sale(consumption, customer_id=customer_id, security_id=security_id)
        uow.commit()

        adjustments = (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .all()
        )
        assert len(adjustments) == 1


# --- on_buy_fill (forward window) ---------------------------------------------------------------


def test_on_buy_fill_adjusts_an_earlier_loss_sale_in_the_forward_window() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        original_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        consumption = _consume(
            uow, tax_lot=original_lot, realized_gain_loss=Money("-200.00"),
            sale_date=date(2026, 2, 1)
        )

        # Replacement buy arrives after the loss sale: the forward-window side.
        new_lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("2000.00"), acquired_at=date(2026, 2, 10),
        )

        WashSaleService(uow).on_buy_fill(new_lot)
        uow.commit()

        adjustment = (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one()
        )
        assert adjustment.disallowed_amount == Money("200.00")
        assert adjustment.replacement_tax_lot_id == new_lot.id


def test_on_buy_fill_never_treats_a_lot_as_its_own_replacement() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_customer(uow)
        security_id = _insert_security(uow)
        lot = _open_lot(
            uow, customer_id=customer_id, security_id=security_id,
            quantity=Units("10"), cost_basis=Money("1000.00"), acquired_at=date(2026, 1, 1),
        )
        # Consumption's tax_lot_id is the new lot itself; must be skipped, not adjusted.
        consumption = _consume(
            uow, tax_lot=lot, realized_gain_loss=Money("-50.00"), sale_date=date(2026, 1, 1)
        )

        WashSaleService(uow).on_buy_fill(lot)
        uow.commit()

        assert (
            uow.session.query(WashSaleAdjustment)
            .filter_by(original_lot_consumption_id=consumption.id)
            .one_or_none()
        ) is None
