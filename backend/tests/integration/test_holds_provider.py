"""`OrderHoldsProvider` (S1 §5's `HoldsProvider` contract, owned by S3) against real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_projection_service import OrderProjectionService
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

ORDER_TABLES = [*LEDGER_TABLES, Order.__table__, OrderEvent.__table__, ApprovalHold.__table__]

NOW = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)


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


def _submit(uow: OrdersUnitOfWork, order: Order) -> None:
    hold_service = ApprovalHoldService(uow)
    projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
    projection.apply_new_event(
        order,
        OrderEvent(
            order_id=order.id,
            seq=1,
            event_type=OrderEventType.SUBMITTED,
            payload={},
            recorded_at=NOW,
        ),
    )


def _fill(uow: OrdersUnitOfWork, order: Order, *, seq: int, quantity: str, price: str) -> None:
    hold_service = ApprovalHoldService(uow)
    projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
    projection.apply_new_event(
        order,
        OrderEvent(
            order_id=order.id,
            seq=seq,
            event_type=OrderEventType.FILL,
            execution_id=f"exec-{order.id}-{seq}",
            payload={"quantity": quantity, "price": price},
            recorded_at=NOW,
        ),
    )


def test_holds_sums_active_approval_holds_only() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=uuid.uuid4(),
            side=OrderSide.BUY,
            quantity_requested=Units("10"),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("500.00")
        )
        uow.commit()

    with _owner_uow() as uow:
        assert OrderHoldsProvider(uow).holds(customer_id) == Money("500.00")


def test_open_buy_commitments_uses_the_original_hold_amount_before_any_fill() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=uuid.uuid4(),
            side=OrderSide.BUY,
            quantity_requested=Units("10"),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )
        _submit(uow, order)
        uow.commit()

    with _owner_uow() as uow:
        commitments = OrderHoldsProvider(uow).open_buy_commitments(customer_id)

    assert commitments == Money("1000.00")


def test_open_buy_commitments_values_the_unfilled_remainder_at_the_average_fill_price() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=uuid.uuid4(),
            side=OrderSide.BUY,
            quantity_requested=Units("10"),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )
        _submit(uow, order)
        _fill(uow, order, seq=2, quantity="4", price="100")
        uow.commit()

    with _owner_uow() as uow:
        commitments = OrderHoldsProvider(uow).open_buy_commitments(customer_id)

    # 6 units remaining, valued at the realized $100 average fill price -- not the stale $1000
    # (=10 * $100 reference) hold estimate.
    assert commitments == Money("600.00")


def test_open_buy_commitments_excludes_fully_filled_and_terminal_orders() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=uuid.uuid4(),
            side=OrderSide.BUY,
            quantity_requested=Units("10"),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )
        _submit(uow, order)
        _fill(uow, order, seq=2, quantity="10", price="100")
        uow.commit()

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None and order.status is OrderStatus.FILLED
        commitments = OrderHoldsProvider(uow).open_buy_commitments(customer_id)

    assert commitments == Money("0.00")
