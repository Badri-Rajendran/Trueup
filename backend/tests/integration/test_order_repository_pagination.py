"""`OrderRepository.list_for_customer` (S12 §8) — keyset-pagination stability against real
Postgres: paging with `limit=2` across 5 seeded orders survives a new order inserted mid-walk
into an already-yielded page's position, with no repeated or skipped row."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import DbRole
from app.core.money import Units
from app.core.pagination import decode_cursor, paginate
from app.core.uow import SessionRole
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

ORDER_TABLES = [*LEDGER_TABLES, Order.__table__]


@pytest.fixture
def order_tables(owner_engine):
    for table in ORDER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(ORDER_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("order_tables")


def _order(customer_id: uuid.UUID, *, created_at: datetime) -> Order:
    order_id = uuid.uuid4()
    return Order(
        id=order_id,
        customer_id=customer_id,
        security_id=uuid.uuid4(),
        side=OrderSide.BUY,
        quantity_requested=Units("10"),
        status=OrderStatus.APPROVED,
        filled_quantity=Units("0"),
        client_order_id=derive_client_order_id(order_id),
        created_at=created_at,
    )


def _cursor_key(order: Order) -> tuple[str, str]:
    return (order.created_at.isoformat(), str(order.id))


def _decode_after(raw_cursor: str) -> tuple[datetime, uuid.UUID]:
    decoded = decode_cursor(raw_cursor)
    return datetime.fromisoformat(decoded[0]), uuid.UUID(decoded[1])  # type: ignore[arg-type]


def test_list_for_customer_pagination_is_stable_under_a_mid_walk_insert(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    base = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    # DESC order: seeded[0] (base) is newest ... seeded[4] (base - 4min) is oldest.
    seeded = [_order(customer_id, created_at=base - timedelta(minutes=i)) for i in range(5)]
    db_committing.add_all(seeded)
    db_committing.commit()

    def _uow() -> OrdersUnitOfWork:
        return OrdersUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        )

    # `.items` are attached to each `with` block's own session; ids are extracted before it
    # closes (closing expires -- and detaches access to -- the loaded ORM instances).
    with _uow() as uow:
        rows = uow.orders.list_for_customer(customer_id, limit=2)
        page1 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page1_ids = [o.id for o in page1.items]
    assert page1_ids == [seeded[0].id, seeded[1].id]
    assert page1.next_cursor is not None

    # Insert a new order whose `created_at` falls strictly between seeded[0] and seeded[1] --
    # into page 1's already-yielded position -- after page 1 has already been fetched.
    mid_insert = _order(customer_id, created_at=base - timedelta(seconds=30))
    db_committing.add(mid_insert)
    db_committing.commit()

    after = _decode_after(page1.next_cursor)
    with _uow() as uow:
        rows = uow.orders.list_for_customer(customer_id, limit=2, after=after)
        page2 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page2_ids = [o.id for o in page2.items]
    assert page2_ids == [seeded[2].id, seeded[3].id]
    assert page2.next_cursor is not None

    after = _decode_after(page2.next_cursor)
    with _uow() as uow:
        rows = uow.orders.list_for_customer(customer_id, limit=2, after=after)
        page3 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page3_ids = [o.id for o in page3.items]
    assert page3_ids == [seeded[4].id]
    assert page3.next_cursor is None

    walked_ids = [*page1_ids, *page2_ids, *page3_ids]
    assert walked_ids == [o.id for o in seeded]  # every seeded row exactly once, in order
    assert mid_insert.id not in walked_ids  # the mid-walk insert never leaks into the walk
