"""F12/I3 (S0 §10.1 audit): DB-level DELETE/UPDATE revocation on six money-bearing tables that
shipped with no REVOKE (`tax_lot`, `lot_consumption`, `wash_sale_adjustment`, `approval_hold`,
`high_water_mark`, `fee_charge`)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from app.core.db import DbRole
from app.core.uow import SessionRole, UnitOfWork
from app.models.fees.fee_charge import FeeCharge
from app.models.fees.high_water_mark import HighWaterMark
from app.models.identity.customer import Customer
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security
from app.models.ops.inbound_event import InboundEvent
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.models.orders.order_event import OrderEvent

_TABLES = [
    Customer.__table__,
    Security.__table__,
    InboundEvent.__table__,
    JournalEntry.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
    ApprovalHold.__table__,
    HighWaterMark.__table__,
    FeeCharge.__table__,
]


@pytest.fixture(autouse=True)
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _cannot_delete(table_name: str) -> None:
    # table_name is always a hardcoded literal, never user input.
    statement = text(f'DELETE FROM "{table_name}" WHERE id = :id')  # noqa: S608
    with (
        UnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(statement, {"id": uuid.uuid4()})


def test_app_role_cannot_delete_a_tax_lot() -> None:
    _cannot_delete("tax_lot")


def test_app_role_cannot_delete_a_lot_consumption() -> None:
    _cannot_delete("lot_consumption")


def test_app_role_cannot_update_a_wash_sale_adjustment() -> None:
    with (
        UnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow,
        pytest.raises(DBAPIError),
    ):
        uow.session.execute(
            text("UPDATE wash_sale_adjustment SET disallowed_amount = 1 WHERE id = :id"),
            {"id": uuid.uuid4()},
        )


def test_app_role_cannot_delete_a_wash_sale_adjustment() -> None:
    _cannot_delete("wash_sale_adjustment")


def test_app_role_cannot_delete_an_approval_hold() -> None:
    _cannot_delete("approval_hold")


def test_app_role_cannot_delete_a_high_water_mark() -> None:
    _cannot_delete("high_water_mark")


def test_app_role_cannot_delete_a_fee_charge() -> None:
    _cannot_delete("fee_charge")
