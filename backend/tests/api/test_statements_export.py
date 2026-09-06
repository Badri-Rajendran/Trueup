"""`GET /api/v1/statements/<period>/export` (S8 §5, FR-36) via the Flask test client: the CSV
export happy path (wash-sale-adjusted figures, a provisional row included), the "not yet
published" edge case (S8 §6 case 1), authn/ownership, and throttling.
"""

from __future__ import annotations

import csv
import io
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.money import Money, Units
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.models.restatement.published_snapshot import PublishedSnapshot

CUSTOMER_EMAIL = "export-customer@trueup.example"
PASSWORD = "correct-horse-battery"

PERIOD_START = date(2026, 1, 1)
PERIOD_END = date(2026, 1, 31)

EXPORT_TABLES = [
    Security.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    PublishedSnapshot.__table__,
]


@pytest.fixture(autouse=True)
def _export_tables(owner_engine: Engine) -> Iterator[None]:
    for table in EXPORT_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(EXPORT_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _register_and_login(client: FlaskClient) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": CUSTOMER_EMAIL, "password": PASSWORD}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post(
        "/api/v1/auth/login", json={"email": CUSTOMER_EMAIL, "password": PASSWORD}
    )
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _publish_snapshot(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        session.add(
            PublishedSnapshot(
                customer_id=customer_id,
                period_start=PERIOD_START,
                period_end=PERIOD_END,
                publish_watermark=datetime(2026, 2, 1, tzinfo=UTC),
                twr=Decimal("0.0100000000"),
                balance=Money("5000.00"),
                holdings_json={},
                published_at=datetime(2026, 2, 1, tzinfo=UTC),
            )
        )
        session.commit()
    finally:
        session.close()


def _seed_realized_lot(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security = Security(symbol="EXPT", name="Export Co.", asset_class=SecurityAssetClass.EQUITY)
        session.add(security)
        session.flush()

        buy_order = Order(
            customer_id=customer_id, security_id=security.id, side=OrderSide.BUY,
            quantity_requested=Units("10"), status=OrderStatus.FILLED, filled_quantity=Units("10"),
            client_order_id=derive_client_order_id(uuid.uuid4()),
        )
        session.add(buy_order)
        session.flush()
        session.add(
            OrderEvent(
                order_id=buy_order.id, seq=1, event_type=OrderEventType.FILL,
                execution_id="buy-exp-1", payload={},
            )
        )
        session.flush()

        lot = TaxLot(
            customer_id=customer_id,
            security_id=security.id,
            opening_fill_execution_id="buy-exp-1",
            quantity_opened=Units("10"),
            quantity_remaining=Units("5"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("450.00"),
            acquired_at=date(2026, 1, 3),
            designation=LotDesignation.UNSPECIFIED,
            designation_window_closes_at=datetime(2026, 1, 6, 16, 0, tzinfo=UTC),
        )
        session.add(lot)
        session.flush()

        sell_order = Order(
            customer_id=customer_id, security_id=security.id, side=OrderSide.SELL,
            quantity_requested=Units("5"), status=OrderStatus.FILLED, filled_quantity=Units("5"),
            client_order_id=derive_client_order_id(uuid.uuid4()),
        )
        session.add(sell_order)
        session.flush()
        session.add(
            OrderEvent(
                order_id=sell_order.id, seq=1, event_type=OrderEventType.FILL,
                execution_id="sell-exp-1", payload={},
            )
        )
        session.flush()
        session.add(
            LotConsumption(
                closing_fill_execution_id="sell-exp-1",
                tax_lot_id=lot.id,
                quantity_consumed=Units("5"),
                realized_gain_loss=Money("-25.00"),
                is_provisional=True,
                sale_date=date(2026, 1, 15),
            )
        )
        session.commit()
    finally:
        session.close()


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/statements/{PERIOD_START.isoformat()}/export")

    assert response.status_code == 401


def test_unpublished_period_returns_a_clear_not_yet_published_error(
    api_client: FlaskClient,
) -> None:
    _register_and_login(api_client)

    response = api_client.get(f"/api/v1/statements/{PERIOD_START.isoformat()}/export")

    assert response.status_code == 404
    body = response.get_json()
    assert body["code"] == "statement_not_published"


def test_export_happy_path_includes_the_adjusted_basis_and_provisional_flag(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    _publish_snapshot(owner_engine, uuid.UUID(customer_id))
    _seed_realized_lot(owner_engine, uuid.UUID(customer_id))

    response = api_client.get(f"/api/v1/statements/{PERIOD_START.isoformat()}/export")

    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment" in response.headers["Content-Disposition"]
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True))))
    assert rows[0] == [
        "symbol",
        "quantity_consumed",
        "original_cost_basis",
        "adjusted_basis",
        "realized_gain_loss",
        "is_provisional",
    ]
    assert rows[1] == ["EXPT", "5.000000", "1000.0000", "450.0000", "-25.0000", "true"]


def test_is_throttled(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    last_response = None
    for _ in range(31):
        last_response = api_client.get(f"/api/v1/statements/{PERIOD_START.isoformat()}/export")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
