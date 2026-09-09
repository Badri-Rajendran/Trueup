"""`TaxLotRepository.list_for_customer` (S12 §8) — keyset-pagination stability against real
Postgres: paging with `limit=2` across 5 seeded lots survives a new lot inserted mid-walk into an
already-yielded page's position, with no repeated or skipped row."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.pagination import decode_cursor, paginate
from app.core.uow import SessionRole
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.lots.uow import LotsUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

TAX_LOT_TABLES = [*LEDGER_TABLES, Security.__table__, Order.__table__, OrderEvent.__table__,
                  TaxLot.__table__]


@pytest.fixture
def tax_lot_tables(owner_engine):
    for table in TAX_LOT_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(TAX_LOT_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("tax_lot_tables")


def _seed_lot(db_committing, *, customer_id: uuid.UUID, security_id: uuid.UUID,
              acquired_at: date, lot_id: uuid.UUID | None = None) -> TaxLot:
    execution_id = f"exec-{uuid.uuid4()}"
    order_id = uuid.uuid4()
    order = Order(
        id=order_id,
        customer_id=customer_id,
        security_id=security_id,
        side=OrderSide.BUY,
        quantity_requested=Units("10"),
        status=OrderStatus.FILLED,
        filled_quantity=Units("10"),
        client_order_id=derive_client_order_id(order_id),
    )
    db_committing.add(order)
    db_committing.flush()
    db_committing.add(
        OrderEvent(
            order_id=order_id, seq=1, event_type=OrderEventType.FILL,
            execution_id=execution_id, payload={},
        )
    )
    db_committing.flush()

    lot = TaxLot(
        id=lot_id if lot_id is not None else uuid.uuid4(),
        customer_id=customer_id,
        security_id=security_id,
        opening_fill_execution_id=execution_id,
        quantity_opened=Units("10"),
        quantity_remaining=Units("10"),
        original_cost_basis=Money("1000.00"),
        adjusted_basis=Money("1000.00"),
        acquired_at=acquired_at,
        designation=LotDesignation.UNSPECIFIED,
        designation_window_closes_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_committing.add(lot)
    db_committing.commit()
    return lot


def _cursor_key(lot: TaxLot) -> tuple[str, str]:
    return (lot.acquired_at.isoformat(), str(lot.id))


def _decode_after(raw_cursor: str) -> tuple[date, uuid.UUID]:
    decoded = decode_cursor(raw_cursor)
    return date.fromisoformat(decoded[0]), uuid.UUID(decoded[1])  # type: ignore[arg-type]


def test_list_for_customer_pagination_is_stable_under_a_mid_walk_insert(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    security = Security(symbol="PGSTB", name="Pagination Stability Co.",
                         asset_class=SecurityAssetClass.EQUITY)
    db_committing.add(security)
    db_committing.commit()

    base = date(2026, 1, 1)
    # ASC order: seeded[0] (base) is oldest ... seeded[4] (base + 4 days) is newest.
    seeded = [
        _seed_lot(db_committing, customer_id=customer_id, security_id=security.id,
                  acquired_at=base + timedelta(days=i))
        for i in range(5)
    ]

    def _uow() -> LotsUnitOfWork:
        return LotsUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        )

    # `.items` are attached to each `with` block's own session; ids are extracted before it
    # closes (closing expires -- and detaches access to -- the loaded ORM instances).
    with _uow() as uow:
        rows = uow.tax_lots.list_for_customer(customer_id, limit=2)
        page1 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page1_ids = [lot.id for lot in page1.items]
    assert page1_ids == [seeded[0].id, seeded[1].id]
    assert page1.next_cursor is not None

    # A same-day lot ties on `acquired_at` alone; seed it exactly on seeded[1]'s date with a
    # deliberately-minimal `id` (guaranteed less than any uuid4) so the `(acquired_at, id)`
    # tiebreak places it strictly before seeded[1] -- into page 1's already-yielded position --
    # after page 1 has already been fetched.
    mid_insert = _seed_lot(
        db_committing, customer_id=customer_id, security_id=security.id,
        acquired_at=seeded[1].acquired_at, lot_id=uuid.UUID(int=0),
    )

    after = _decode_after(page1.next_cursor)
    with _uow() as uow:
        rows = uow.tax_lots.list_for_customer(customer_id, limit=2, after=after)
        page2 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page2_ids = [lot.id for lot in page2.items]
    assert page2_ids == [seeded[2].id, seeded[3].id]
    assert page2.next_cursor is not None

    after = _decode_after(page2.next_cursor)
    with _uow() as uow:
        rows = uow.tax_lots.list_for_customer(customer_id, limit=2, after=after)
        page3 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page3_ids = [lot.id for lot in page3.items]
    assert page3_ids == [seeded[4].id]
    assert page3.next_cursor is None

    walked_ids = [*page1_ids, *page2_ids, *page3_ids]
    assert walked_ids == [lot.id for lot in seeded]  # every seeded row exactly once, in order
    assert mid_insert.id not in walked_ids  # the mid-walk insert never leaks into the walk
