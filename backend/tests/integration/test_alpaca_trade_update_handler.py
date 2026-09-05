"""`AlpacaTradeUpdateHandler` (S0 §6 dispatch, ADR 22) against real PostgreSQL: mapping Alpaca's
own event vocabulary onto this system's `OrderEventType`, and foundation spec §10 case 4's
"unmatched entity" path.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.clock import InMemoryTradingCalendar, MarketClock
from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.order_projection_service import OrderProjectionService
from app.services.orders.trade_update_handler import (
    AlpacaTradeUpdateHandler,
    OrderNotFoundForClientOrderIdError,
)
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

# S5's tables added alongside S3's own: a `fill` event now also drives `LotConsumptionService`
# (`app.services.orders.trade_update_handler`'s own module docstring), which opens/consumes
# `tax_lot`/`lot_consumption`/`wash_sale_adjustment` rows against a real `security` row.
ORDER_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    Order.__table__,
    OrderEvent.__table__,
    ApprovalHold.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
]

NOW = datetime(2026, 9, 5, 16, 0, tzinfo=UTC)


@pytest.fixture
def order_tables(owner_engine):
    for table in ORDER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(ORDER_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("order_tables")


def _owner_uow() -> OrdersUnitOfWork:
    return OrdersUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _market_clock_factory(_uow: OrdersUnitOfWork) -> MarketClock:
    """A trivial in-memory calendar (no holidays) rather than the real `CachedTradingCalendar` --
    this test has no reason to seed `market_calendar_cache` rows just to exercise fill handling."""
    return MarketClock(InMemoryTradingCalendar())


def _seed_submitted_order(quantity: str = "10") -> tuple[uuid.UUID, str, uuid.UUID]:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security = Security(
            symbol=f"TST{uuid.uuid4().hex[:6]}",
            name="Test Co",
            asset_class=SecurityAssetClass.EQUITY,
        )
        uow.session.add(security)
        uow.session.add(Account.create(AccountRole.CASH, customer_id=customer_id))
        uow.session.add(Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id))
        uow.session.flush()

        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=security.id,
            side=OrderSide.BUY,
            quantity_requested=Units(quantity),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )
        hold_service = ApprovalHoldService(uow)
        projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
        projection.apply_new_event(
            order,
            OrderEvent(
                order_id=order_id,
                seq=1,
                event_type=OrderEventType.SUBMITTED,
                payload={},
                recorded_at=NOW,
            ),
        )
        uow.commit()
    return order_id, order.client_order_id, security.id


def _handler() -> AlpacaTradeUpdateHandler:
    return AlpacaTradeUpdateHandler(
        uow_factory=_owner_uow, now=lambda: NOW, market_clock_factory=_market_clock_factory
    )


def test_new_event_maps_to_accepted() -> None:
    order_id, client_order_id, _security_id = _seed_submitted_order()

    _handler().handle(
        {
            "event": "new",
            "execution_id": None,
            "order": {"id": "broker-1", "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None
        assert order.status is OrderStatus.ACCEPTED


def test_fill_event_updates_filled_quantity_and_average_price() -> None:
    order_id, client_order_id, security_id = _seed_submitted_order(quantity="10")

    _handler().handle(
        {
            "event": "fill",
            "execution_id": "exec-abc",
            "order": {"id": "broker-1", "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
            "qty": "10",
            "price": "50",
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None
        assert order.status is OrderStatus.FILLED
        assert order.filled_quantity == Units("10")
        assert order.average_fill_price is not None
        events = uow.order_events.list_for_order(order_id)
        assert any(e.execution_id == "exec-abc" for e in events)

        # S5: a buy fill also opens a tax lot (LotConsumptionService, wired from this handler).
        lot = (
            uow.session.query(TaxLot)
            .filter_by(opening_fill_execution_id="exec-abc")
            .one()
        )
        assert lot.customer_id == order.customer_id
        assert lot.security_id == security_id
        assert lot.quantity_remaining == Units("10")
        assert lot.original_cost_basis == Money("500.00")


def test_canceled_event_marks_the_order_canceled() -> None:
    order_id, client_order_id, _security_id = _seed_submitted_order()

    _handler().handle(
        {
            "event": "canceled",
            "execution_id": None,
            "order": {"id": "broker-1", "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None
        assert order.status is OrderStatus.CANCELED


def test_untracked_alpaca_event_is_a_no_op() -> None:
    order_id, client_order_id, _security_id = _seed_submitted_order()

    _handler().handle(
        {
            "event": "pending_replace",
            "execution_id": None,
            "order": {"id": "broker-1", "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None
        assert order.status is OrderStatus.SUBMITTED  # unchanged


def test_unknown_client_order_id_raises_for_the_outbox_to_retry_and_dead_letter() -> None:
    with pytest.raises(OrderNotFoundForClientOrderIdError):
        _handler().handle(
            {
                "event": "fill",
                "execution_id": "exec-orphan",
                "order": {"id": "broker-1", "client_order_id": "trueup-does-not-exist"},
                "timestamp": NOW.isoformat(),
                "qty": "1",
                "price": "1",
            }
        )
