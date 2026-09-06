"""PostgreSQL-only invariants for S3's schema: RLS on `order`/`approval_hold` (S0 §7.3, ADR 17),
append-only enforcement on `order_event` (ADR 7), and the unique constraints §3's dedupe/one-hold-
per-order guarantees depend on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole, UnitOfWork
from app.models.orders.approval_hold import ApprovalHold, ApprovalHoldStatus
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from tests.integration.conftest import LEDGER_TABLES, insert_customer

ORDER_TABLES = [*LEDGER_TABLES, Order.__table__, OrderEvent.__table__, ApprovalHold.__table__]


@pytest.fixture
def order_tables(owner_engine):
    for table in ORDER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(ORDER_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("order_tables")


def _order(customer_id: uuid.UUID, *, quantity: str = "10") -> Order:
    order_id = uuid.uuid4()
    return Order(
        id=order_id,
        customer_id=customer_id,
        security_id=uuid.uuid4(),
        side=OrderSide.BUY,
        quantity_requested=Units(quantity),
        status=OrderStatus.APPROVED,
        filled_quantity=Units("0"),
        client_order_id=derive_client_order_id(order_id),
    )


def test_customer_session_cannot_see_another_customers_order(db_committing) -> None:
    customer_a = insert_customer(db_committing)
    customer_b = insert_customer(db_committing)
    order_a = _order(customer_a)
    order_b = _order(customer_b)
    db_committing.add_all([order_a, order_b])
    db_committing.commit()

    with UnitOfWork(customer_id=customer_a, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow:
        visible = {row.id for row in uow.session.execute(select(Order)).scalars().all()}

    assert visible == {order_a.id}


def test_adviser_session_can_read_orders_across_customers(db_committing) -> None:
    customer_a = insert_customer(db_committing)
    customer_b = insert_customer(db_committing)
    db_committing.add_all([_order(customer_a), _order(customer_b)])
    db_committing.commit()

    with UnitOfWork(customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP) as uow:
        visible_customers = {
            row.customer_id for row in uow.session.execute(select(Order)).scalars().all()
        }

    assert {customer_a, customer_b} <= visible_customers


def test_customer_session_cannot_see_another_customers_approval_hold(db_committing) -> None:
    customer_a = insert_customer(db_committing)
    customer_b = insert_customer(db_committing)
    order_a = _order(customer_a)
    order_b = _order(customer_b)
    db_committing.add_all([order_a, order_b])
    db_committing.flush()
    hold_a = ApprovalHold(order_id=order_a.id, customer_id=customer_a, amount_money=Money("100"))
    hold_b = ApprovalHold(order_id=order_b.id, customer_id=customer_b, amount_money=Money("200"))
    db_committing.add_all([hold_a, hold_b])
    db_committing.commit()

    with UnitOfWork(customer_id=customer_a, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow:
        visible = {row.id for row in uow.session.execute(select(ApprovalHold)).scalars().all()}

    assert visible == {hold_a.id}


def test_app_role_cannot_update_an_order_event(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    event = OrderEvent(
        order_id=order.id,
        seq=1,
        event_type=OrderEventType.SUBMITTED,
        payload={},
        recorded_at=datetime.now(UTC),
    )
    db_committing.add(event)
    db_committing.commit()

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(
            OrderEvent.__table__.update().where(OrderEvent.id == event.id).values(seq=2)
        )


def test_app_role_cannot_delete_an_order_event(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    event = OrderEvent(
        order_id=order.id,
        seq=1,
        event_type=OrderEventType.SUBMITTED,
        payload={},
        recorded_at=datetime.now(UTC),
    )
    db_committing.add(event)
    db_committing.commit()

    with (
        UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(OrderEvent.__table__.delete().where(OrderEvent.id == event.id))


def test_order_event_seq_is_unique_per_order(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    db_committing.add(
        OrderEvent(
            order_id=order.id,
            seq=1,
            event_type=OrderEventType.SUBMITTED,
            payload={},
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.commit()

    db_committing.add(
        OrderEvent(
            order_id=order.id,
            seq=1,
            event_type=OrderEventType.ACCEPTED,
            payload={},
            recorded_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_order_event_execution_id_is_globally_unique(db_committing) -> None:
    """ADR 7's dedupe key -- a replayed fill webhook's `execution_id` collides regardless of
    which order it names."""
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    db_committing.add(
        OrderEvent(
            order_id=order.id,
            seq=1,
            event_type=OrderEventType.FILL,
            execution_id="exec-dup",
            payload={"quantity": "1", "price": "10"},
            recorded_at=datetime.now(UTC),
        )
    )
    db_committing.commit()

    db_committing.add(
        OrderEvent(
            order_id=order.id,
            seq=2,
            event_type=OrderEventType.FILL,
            execution_id="exec-dup",
            payload={"quantity": "1", "price": "10"},
            recorded_at=datetime.now(UTC),
        )
    )
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_approval_hold_order_id_is_unique(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    db_committing.add(
        ApprovalHold(order_id=order.id, customer_id=customer_id, amount_money=Money("100"))
    )
    db_committing.commit()

    db_committing.add(
        ApprovalHold(order_id=order.id, customer_id=customer_id, amount_money=Money("50"))
    )
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_order_client_order_id_is_unique(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.commit()

    duplicate = _order(customer_id)
    duplicate.client_order_id = order.client_order_id
    db_committing.add(duplicate)
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_active_hold_status_default_and_release_reason_starts_unset(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    order = _order(customer_id)
    db_committing.add(order)
    db_committing.flush()
    hold = ApprovalHold(order_id=order.id, customer_id=customer_id, amount_money=Money("500"))
    db_committing.add(hold)
    db_committing.commit()

    db_committing.refresh(hold)
    assert hold.status is ApprovalHoldStatus.ACTIVE
    assert hold.release_reason is None
    assert hold.released_at is None
