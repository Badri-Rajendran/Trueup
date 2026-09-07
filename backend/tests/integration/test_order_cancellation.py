"""`OrderService.request_cancel` (ADR 25) against real PostgreSQL: the broker request itself, its
idempotency, its rejection paths, and -- the critical regression guard for the whole design -- a
`fill` trade-update racing and winning against a pending cancel request.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

from app.core.clock import InMemoryTradingCalendar, MarketClock
from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.integrations.fake.fake_broker import FakeBrokerAdapter
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.orders.approval_hold import (
    ApprovalHold,
    ApprovalHoldReleaseReason,
    ApprovalHoldStatus,
)
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_projection_service import OrderProjectionService
from app.services.orders.order_service import (
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderService,
)
from app.services.orders.trade_update_handler import AlpacaTradeUpdateHandler
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

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

NOW = datetime(2026, 9, 6, 14, 0, tzinfo=UTC)
BROKER_ORDER_ID = "broker-order-cancel-1"


@pytest.fixture
def order_tables(owner_engine):
    for table in ORDER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(ORDER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("order_tables")


def _owner_uow() -> OrdersUnitOfWork:
    return OrdersUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _market_clock_factory(_uow: OrdersUnitOfWork) -> MarketClock:
    return MarketClock(InMemoryTradingCalendar())


def _handler() -> AlpacaTradeUpdateHandler:
    return AlpacaTradeUpdateHandler(
        uow_factory=_owner_uow, now=lambda: NOW, market_clock_factory=_market_clock_factory
    )


def _seed_order(
    *, status: OrderStatus, quantity: str = "10", with_submitted_event: bool = False
) -> tuple[uuid.UUID, str, uuid.UUID]:
    """Seeds an order (and its hold) at `status`; `with_submitted_event` additionally records the
    `submitted` `order_event` carrying `BROKER_ORDER_ID`, mirroring `submit_to_broker`."""
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
            status=status,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )

        if with_submitted_event:
            hold_service = ApprovalHoldService(uow)
            projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
            projection.apply_new_event(
                order,
                OrderEvent(
                    order_id=order_id,
                    seq=1,
                    event_type=OrderEventType.SUBMITTED,
                    payload={"broker_order_id": BROKER_ORDER_ID},
                    recorded_at=NOW,
                ),
            )
        uow.commit()
    return order_id, order.client_order_id, security.id


def _service(uow: OrdersUnitOfWork) -> OrderService:
    # request_cancel needs neither hold_service nor cash_policy; approve/create do, so both are
    # still required constructor args -- pass through the real ones for shape consistency.
    return OrderService(
        uow,
        hold_service=ApprovalHoldService(uow),
        cash_policy=CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow)),
        approval_threshold_usd=Money("10000.00"),
        now=lambda: NOW,
    )


def test_request_cancel_calls_the_broker_and_does_not_change_status() -> None:
    order_id, _client_order_id, _security_id = _seed_order(
        status=OrderStatus.SUBMITTED, with_submitted_event=True
    )
    broker = FakeBrokerAdapter()

    with _owner_uow() as uow:
        order = _service(uow).request_cancel(order_id, broker=broker)
        assert order.status is OrderStatus.SUBMITTED  # unchanged -- only the websocket moves it
        uow.commit()

    assert broker.cancel_requests == [BROKER_ORDER_ID]

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None and order.status is OrderStatus.SUBMITTED


def test_request_cancel_is_idempotent_while_still_cancellable() -> None:
    order_id, _client_order_id, _security_id = _seed_order(
        status=OrderStatus.SUBMITTED, with_submitted_event=True
    )
    broker = FakeBrokerAdapter()

    with _owner_uow() as uow:
        _service(uow).request_cancel(order_id, broker=broker)
        uow.commit()
    with _owner_uow() as uow:
        _service(uow).request_cancel(order_id, broker=broker)
        uow.commit()

    assert broker.cancel_requests == [BROKER_ORDER_ID, BROKER_ORDER_ID]


@pytest.mark.parametrize(
    "status",
    [
        OrderStatus.DRAFT,
        OrderStatus.AWAITING_APPROVAL,
        OrderStatus.APPROVED,
        OrderStatus.FILLED,
        OrderStatus.REJECTED,
        OrderStatus.CANCELED,
        OrderStatus.EXPIRED,
    ],
)
def test_request_cancel_rejects_every_non_cancellable_status(status: OrderStatus) -> None:
    order_id, _client_order_id, _security_id = _seed_order(status=status)
    broker = FakeBrokerAdapter()

    with _owner_uow() as uow, pytest.raises(OrderNotCancellableError):
        _service(uow).request_cancel(order_id, broker=broker)

    assert broker.cancel_requests == []


def test_request_cancel_rejects_an_unknown_order() -> None:
    broker = FakeBrokerAdapter()
    with _owner_uow() as uow, pytest.raises(OrderNotFoundError):
        _service(uow).request_cancel(uuid.uuid4(), broker=broker)


def test_fill_racing_a_pending_cancel_still_lands_on_filled_not_canceled() -> None:
    """The critical regression guard for ADR 25: `request_cancel` never writes `order.status`, so
    a `fill` that arrives after the cancel was requested still wins."""
    order_id, client_order_id, _security_id = _seed_order(
        status=OrderStatus.SUBMITTED, with_submitted_event=True
    )
    broker = FakeBrokerAdapter()

    with _owner_uow() as uow:
        _service(uow).request_cancel(order_id, broker=broker)
        uow.commit()
    assert broker.cancel_requests == [BROKER_ORDER_ID]

    _handler().handle(
        {
            "event": "fill",
            "execution_id": "exec-races-cancel-1",
            "order": {"id": BROKER_ORDER_ID, "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
            "qty": "10",
            "price": "50",
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None
        assert order.status is OrderStatus.FILLED  # not canceled
        assert order.filled_quantity == Units("10")


def test_hold_is_released_only_by_the_broker_confirmed_cancel_never_by_the_request() -> None:
    order_id, client_order_id, _security_id = _seed_order(
        status=OrderStatus.SUBMITTED, with_submitted_event=True
    )
    broker = FakeBrokerAdapter()

    with _owner_uow() as uow:
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert hold is not None
        # `submitted` already released it -- request_cancel starts from an already-released hold.
        assert hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        released_at_before = hold.released_at

    with _owner_uow() as uow:
        _service(uow).request_cancel(order_id, broker=broker)
        uow.commit()

    with _owner_uow() as uow:
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        assert hold.released_at == released_at_before  # request_cancel touched nothing

    _handler().handle(
        {
            "event": "canceled",
            "execution_id": None,
            "order": {"id": BROKER_ORDER_ID, "client_order_id": client_order_id},
            "timestamp": NOW.isoformat(),
        }
    )

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert order is not None and order.status is OrderStatus.CANCELED
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        assert hold.released_at == released_at_before  # the confirmed cancel is a no-op release
