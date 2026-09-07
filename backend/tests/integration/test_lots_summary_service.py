"""`LotsSummaryService` against real Postgres (S8 §3, data owned by S5): market value/unrealized
gain arithmetic for an open lot, the closed-lot-always-null rule, and wash-sale-disallowed
summation across multiple adjustments on one lot."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text

from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.lots.lots_summary_service import LotsSummaryService
from app.services.lots.uow import LotsUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer, insert_inbound_event

LOTS_SUMMARY_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    DailyClose.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
]

AS_OF_DATE = date(2026, 1, 15)


@pytest.fixture
def lots_summary_tables(owner_engine):
    for table in LOTS_SUMMARY_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(LOTS_SUMMARY_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("lots_summary_tables")


def _owner_uow() -> LotsUnitOfWork:
    return LotsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _insert_security(uow: LotsUnitOfWork, *, symbol: str) -> uuid.UUID:
    security = Security(symbol=symbol, name=f"{symbol} Co", asset_class=SecurityAssetClass.EQUITY)
    uow.session.add(security)
    uow.session.flush()
    return security.id


def _insert_fill_order_event(
    uow: LotsUnitOfWork, *, customer_id: uuid.UUID, security_id: uuid.UUID, execution_id: str
) -> None:
    """Standing in for the order/order_event row a real fill creates -- `tax_lot`/`lot_consumption`
    both FK onto `order_event.execution_id`."""
    order = Order(
        customer_id=customer_id,
        security_id=security_id,
        side=OrderSide.BUY,
        quantity_requested=Units("10"),
        status=OrderStatus.FILLED,
        filled_quantity=Units("10"),
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


def _insert_lot(
    uow: LotsUnitOfWork,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    execution_id: str,
    quantity_opened: Units,
    quantity_remaining: Units,
    original_cost_basis: Money,
    adjusted_basis: Money,
) -> TaxLot:
    _insert_fill_order_event(
        uow, customer_id=customer_id, security_id=security_id, execution_id=execution_id
    )
    lot = TaxLot(
        customer_id=customer_id,
        security_id=security_id,
        opening_fill_execution_id=execution_id,
        quantity_opened=quantity_opened,
        quantity_remaining=quantity_remaining,
        original_cost_basis=original_cost_basis,
        adjusted_basis=adjusted_basis,
        acquired_at=date(2026, 1, 5),
        designation=LotDesignation.UNSPECIFIED,
        designation_window_closes_at=datetime(2026, 1, 8, 16, 0, tzinfo=UTC),
    )
    uow.session.add(lot)
    uow.session.flush()
    return lot


def _insert_consumption(
    uow: LotsUnitOfWork,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    tax_lot_id: uuid.UUID,
    execution_id: str,
    quantity_consumed: Units,
    realized_gain_loss: Money,
    sale_date: date,
) -> LotConsumption:
    _insert_fill_order_event(
        uow, customer_id=customer_id, security_id=security_id, execution_id=execution_id
    )
    consumption = LotConsumption(
        closing_fill_execution_id=execution_id,
        tax_lot_id=tax_lot_id,
        quantity_consumed=quantity_consumed,
        realized_gain_loss=realized_gain_loss,
        is_provisional=False,
        sale_date=sale_date,
    )
    uow.session.add(consumption)
    uow.session.flush()
    return consumption


def _insert_daily_close(
    uow: LotsUnitOfWork, *, security_id: uuid.UUID, market_date: date, close_price: Price
) -> None:
    uow.session.add(
        DailyClose(
            security_id=security_id,
            market_date=market_date,
            close_price=close_price,
            source=MarketDataSource.SIMULATED,
            status=DailyCloseStatus.CONFIRMED,
        )
    )
    uow.session.flush()


def _insert_wash_sale_adjustment(
    uow: LotsUnitOfWork,
    *,
    original_lot_consumption_id: uuid.UUID,
    replacement_tax_lot_id: uuid.UUID,
    disallowed_amount: Money,
) -> None:
    inbound_event_id = insert_inbound_event(uow.session)
    journal_entry = JournalEntry(
        entry_type=JournalEntryType.WASH_SALE_ADJUSTMENT,
        effective_date=date(2026, 1, 5),
        source_event_id=inbound_event_id,
    )
    uow.session.add(journal_entry)
    uow.session.flush()
    uow.session.add(
        WashSaleAdjustment(
            original_lot_consumption_id=original_lot_consumption_id,
            replacement_tax_lot_id=replacement_tax_lot_id,
            disallowed_amount=disallowed_amount,
            journal_entry_id=journal_entry.id,
        )
    )
    uow.session.flush()


# --- market value / unrealized gain --------------------------------------------------------


def test_open_lot_gets_market_value_and_unrealized_gain_from_confirmed_close() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow, symbol=f"OPEN{uuid.uuid4().hex[:6]}")
        lot = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-open",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        _insert_daily_close(
            uow, security_id=security_id, market_date=AS_OF_DATE, close_price=Price("110.00")
        )
        lot_id = lot.id
        uow.commit()

    with _owner_uow() as uow:
        summary = LotsSummaryService(uow).summarize(customer_id, as_of_date=AS_OF_DATE)
        items = {item.lot.id: item for item in summary.lots}
        item = items[lot_id]
        assert item.current_price == Price("110.00")
        # 10 units x $110.00 = $1100.00 market value; minus $1000.00 basis = $100.00 gain.
        assert item.market_value == Money("1100.00")
        assert item.unrealized_gain_loss == Money("100.00")


def test_lot_with_no_confirmed_close_has_no_market_value() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow, symbol=f"NOPRICE{uuid.uuid4().hex[:6]}")
        lot = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-noprice",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        lot_id = lot.id
        uow.commit()

    with _owner_uow() as uow:
        summary = LotsSummaryService(uow).summarize(customer_id, as_of_date=AS_OF_DATE)
        items = {item.lot.id: item for item in summary.lots}
        item = items[lot_id]
        assert item.current_price is None
        assert item.market_value is None
        assert item.unrealized_gain_loss is None


def test_closed_lot_market_value_and_unrealized_gain_are_always_none() -> None:
    """S8 §3: a fully-consumed lot has no remaining position to mark to market, even when a
    confirmed close exists for its security."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow, symbol=f"CLOSED{uuid.uuid4().hex[:6]}")
        lot = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-closed",
            quantity_opened=Units("10"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        _insert_daily_close(
            uow, security_id=security_id, market_date=AS_OF_DATE, close_price=Price("110.00")
        )
        lot_id = lot.id
        uow.commit()

    with _owner_uow() as uow:
        summary = LotsSummaryService(uow).summarize(customer_id, as_of_date=AS_OF_DATE)
        items = {item.lot.id: item for item in summary.lots}
        item = items[lot_id]
        assert item.market_value is None
        assert item.unrealized_gain_loss is None


# --- wash-sale-disallowed summation ---------------------------------------------------------


def test_wash_sale_disallowed_sums_multiple_adjustments_on_the_same_lot() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow, symbol=f"WASH{uuid.uuid4().hex[:6]}")

        replacement_lot = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-replacement",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1050.00"),
        )
        sold_lot_1 = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-sold-1",
            quantity_opened=Units("5"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("500.00"),
            adjusted_basis=Money("500.00"),
        )
        sold_lot_2 = _insert_lot(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            execution_id="buy-sold-2",
            quantity_opened=Units("5"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("500.00"),
            adjusted_basis=Money("500.00"),
        )
        consumption_1 = _insert_consumption(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            tax_lot_id=sold_lot_1.id,
            execution_id="sell-1",
            quantity_consumed=Units("5"),
            realized_gain_loss=Money("-30.00"),
            sale_date=date(2026, 1, 4),
        )
        consumption_2 = _insert_consumption(
            uow,
            customer_id=customer_id,
            security_id=security_id,
            tax_lot_id=sold_lot_2.id,
            execution_id="sell-2",
            quantity_consumed=Units("5"),
            realized_gain_loss=Money("-20.00"),
            sale_date=date(2026, 1, 4),
        )
        _insert_wash_sale_adjustment(
            uow,
            original_lot_consumption_id=consumption_1.id,
            replacement_tax_lot_id=replacement_lot.id,
            disallowed_amount=Money("30.00"),
        )
        _insert_wash_sale_adjustment(
            uow,
            original_lot_consumption_id=consumption_2.id,
            replacement_tax_lot_id=replacement_lot.id,
            disallowed_amount=Money("20.00"),
        )
        replacement_lot_id = replacement_lot.id
        sold_lot_1_id = sold_lot_1.id
        uow.commit()

    with _owner_uow() as uow:
        summary = LotsSummaryService(uow).summarize(customer_id, as_of_date=AS_OF_DATE)
        items = {item.lot.id: item for item in summary.lots}
        assert items[replacement_lot_id].wash_sale_disallowed == Money("50.00")
        # Lots with no adjustment against them stay at zero, not missing.
        assert items[sold_lot_1_id].wash_sale_disallowed == Money("0.00")
