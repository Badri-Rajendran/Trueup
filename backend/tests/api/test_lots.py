"""`GET /api/v1/lots` (S8 §3, data owned by S5) via the Flask test client: happy path, wash-sale
adjustment, authn/ownership, and throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.clock import InMemoryTradingCalendar, MarketClock
from app.core.money import Money, Price, Units
from app.models.identity.staff import Staff, StaffRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.identity.auth import hash_password

CUSTOMER_EMAIL = "lots-customer@trueup.example"
OTHER_EMAIL = "lots-other@trueup.example"
STAFF_EMAIL = "lots-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"
PASSWORD = "correct-horse-battery"


@pytest.fixture
def staff_member(owner_engine: Engine) -> Iterator[Staff]:
    session = Session(bind=owner_engine, expire_on_commit=False)
    staff = Staff(
        email=STAFF_EMAIL, password_hash=hash_password(STAFF_PASSWORD), role=StaffRole.adviser
    )
    session.add(staff)
    session.commit()
    yield staff
    session.close()


def _staff_login_with_mfa(client: FlaskClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD}
    )
    assert login_response.status_code == 200
    pending_csrf = login_response.get_json()["csrf_token"]
    secret = client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": pending_csrf}
    ).get_json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": pending_csrf}
    )
    assert verify.status_code == 200


LOTS_TABLES = [
    Security.__table__,
    InboundEvent.__table__,
    JournalEntry.__table__,
    DailyClose.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
]


@pytest.fixture(autouse=True)
def _lots_tables(owner_engine: Engine) -> Iterator[None]:
    for table in LOTS_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(LOTS_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _register_and_login(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL, password: str = PASSWORD
) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _seed_fill_order_event(
    session: Session, *, customer_id: uuid.UUID, security_id: uuid.UUID, execution_id: str
) -> None:
    order = Order(
        customer_id=customer_id,
        security_id=security_id,
        side=OrderSide.BUY,
        quantity_requested=Units("10"),
        status=OrderStatus.FILLED,
        filled_quantity=Units("10"),
        client_order_id=derive_client_order_id(uuid.uuid4()),
    )
    session.add(order)
    session.flush()
    session.add(
        OrderEvent(
            order_id=order.id, seq=1, event_type=OrderEventType.FILL,
            execution_id=execution_id, payload={},
        )
    )
    session.flush()


def _today_market_date() -> date:
    """Resolves "today" through the same UTC -> America/New_York path `MarketClock` gives the
    controller, so seeded `DailyClose` rows never go stale/flaky."""
    return MarketClock(InMemoryTradingCalendar()).market_date(datetime.now(UTC))


def _seed_security(session: Session, *, symbol: str) -> uuid.UUID:
    security = Security(symbol=symbol, name=f"{symbol} Co.", asset_class=SecurityAssetClass.EQUITY)
    session.add(security)
    session.flush()
    return security.id


def _seed_daily_close(
    session: Session, *, security_id: uuid.UUID, market_date: date, close_price: Price
) -> None:
    session.add(
        DailyClose(
            security_id=security_id,
            market_date=market_date,
            close_price=close_price,
            source=MarketDataSource.SIMULATED,
            status=DailyCloseStatus.CONFIRMED,
        )
    )
    session.flush()


def _seed_open_lot(
    session: Session,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    execution_id: str,
    quantity_opened: Units,
    quantity_remaining: Units,
    original_cost_basis: Money,
    adjusted_basis: Money,
    acquired_at: date = date(2026, 1, 5),
) -> TaxLot:
    _seed_fill_order_event(
        session, customer_id=customer_id, security_id=security_id, execution_id=execution_id
    )
    lot = TaxLot(
        customer_id=customer_id,
        security_id=security_id,
        opening_fill_execution_id=execution_id,
        quantity_opened=quantity_opened,
        quantity_remaining=quantity_remaining,
        original_cost_basis=original_cost_basis,
        adjusted_basis=adjusted_basis,
        acquired_at=acquired_at,
        designation=LotDesignation.UNSPECIFIED,
        designation_window_closes_at=datetime(2026, 1, 8, 16, 0, tzinfo=UTC),
    )
    session.add(lot)
    session.flush()
    return lot


def _seed_lot_consumption(
    session: Session,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    tax_lot_id: uuid.UUID,
    execution_id: str,
    quantity_consumed: Units,
    realized_gain_loss: Money,
    sale_date: date,
    is_provisional: bool = False,
) -> LotConsumption:
    _seed_fill_order_event(
        session, customer_id=customer_id, security_id=security_id, execution_id=execution_id
    )
    consumption = LotConsumption(
        closing_fill_execution_id=execution_id,
        tax_lot_id=tax_lot_id,
        quantity_consumed=quantity_consumed,
        realized_gain_loss=realized_gain_loss,
        is_provisional=is_provisional,
        sale_date=sale_date,
    )
    session.add(consumption)
    session.flush()
    return consumption


def _seed_wash_sale_adjustment(
    session: Session,
    *,
    original_lot_consumption_id: uuid.UUID,
    replacement_tax_lot_id: uuid.UUID,
    disallowed_amount: Money,
    effective_date: date,
) -> None:
    inbound_event = InboundEvent(
        source=InboundEventSource.ALPACA,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    session.add(inbound_event)
    session.flush()

    journal_entry = JournalEntry(
        entry_type=JournalEntryType.WASH_SALE_ADJUSTMENT,
        effective_date=effective_date,
        source_event_id=inbound_event.id,
    )
    session.add(journal_entry)
    session.flush()

    session.add(
        WashSaleAdjustment(
            original_lot_consumption_id=original_lot_consumption_id,
            replacement_tax_lot_id=replacement_tax_lot_id,
            disallowed_amount=disallowed_amount,
            journal_entry_id=journal_entry.id,
        )
    )
    session.flush()


def _seed_lot_with_wash_sale_and_provisional_sale(
    owner_engine: Engine, customer_id: uuid.UUID
) -> tuple[uuid.UUID, str]:
    """A lot with an already-adjusted basis (wash sale, S5 §5) and a provisional consumption
    (S5 §3.2)."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security = Security(
            symbol="WASH", name="Wash Sale Co.", asset_class=SecurityAssetClass.EQUITY
        )
        session.add(security)
        session.flush()

        _seed_fill_order_event(
            session, customer_id=customer_id, security_id=security.id, execution_id="buy-1"
        )
        lot = TaxLot(
            customer_id=customer_id,
            security_id=security.id,
            opening_fill_execution_id="buy-1",
            quantity_opened=Units("10"),
            quantity_remaining=Units("5"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("550.00"),
            acquired_at=date(2026, 1, 5),
            designation=LotDesignation.UNSPECIFIED,
            designation_window_closes_at=datetime(2026, 1, 8, 16, 0, tzinfo=UTC),
        )
        session.add(lot)
        session.flush()

        _seed_fill_order_event(
            session, customer_id=customer_id, security_id=security.id, execution_id="sell-1"
        )
        session.add(
            LotConsumption(
                closing_fill_execution_id="sell-1",
                tax_lot_id=lot.id,
                quantity_consumed=Units("5"),
                realized_gain_loss=Money("-50.00"),
                is_provisional=True,
                sale_date=date(2026, 1, 6),
            )
        )
        session.commit()
        return lot.id, str(security.id)
    finally:
        session.close()


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/lots")

    assert response.status_code == 401


def test_customer_sees_own_lots_with_adjusted_basis_and_provisional_flag(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    lot_id, security_id = _seed_lot_with_wash_sale_and_provisional_sale(
        owner_engine, uuid.UUID(customer_id)
    )

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["lots"]) == 1
    lot = body["lots"][0]
    assert lot["id"] == str(lot_id)
    assert lot["security_id"] == security_id
    assert lot["symbol"] == "WASH"
    assert lot["original_cost_basis"] == "1000.0000"
    # Never the raw pre-adjustment basis (S5 §5) -- only the wash-sale-adjusted figure.
    assert lot["adjusted_basis"] == "550.0000"
    assert lot["realized_gain_loss"] == "-50.0000"
    assert lot["is_provisional"] is True
    assert lot["designation"] == "unspecified"
    # No wash-sale adjustment was ever recorded against this lot.
    assert lot["wash_sale_disallowed"] == "0.0000"
    # No DailyClose row exists for WASH -- open lot, but no confirmed price to mark it against.
    assert lot["current_price"] is None
    assert lot["market_value"] is None
    assert lot["unrealized_gain_loss"] is None
    # The seeded provisional sell fill, in full (S8 §3's per-sale detail).
    assert len(lot["consumptions"]) == 1
    consumption = lot["consumptions"][0]
    assert consumption["quantity_consumed"] == "5.000000"
    assert consumption["realized_gain_loss"] == "-50.0000"
    assert consumption["is_provisional"] is True
    assert consumption["sale_date"] == "2026-01-06"


def test_a_customer_never_sees_another_customers_lots(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    _seed_lot_with_wash_sale_and_provisional_sale(owner_engine, uuid.UUID(other_id))
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _register_and_login(api_client)

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    assert response.get_json()["lots"] == []


def test_staff_requires_a_customer_id(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 422


def test_staff_sees_a_named_customers_lots(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})
    _seed_lot_with_wash_sale_and_provisional_sale(owner_engine, uuid.UUID(customer_id))
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/lots?customer_id={customer_id}")

    assert response.status_code == 200
    assert len(response.get_json()["lots"]) == 1


def test_lot_with_no_confirmed_close_has_null_market_value(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security_id = _seed_security(session, symbol="NOCLOSE")
        lot = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-noclose",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    lots = response.get_json()["lots"]
    assert len(lots) == 1
    assert lots[0]["id"] == str(lot.id)
    assert lots[0]["current_price"] is None
    assert lots[0]["market_value"] is None
    assert lots[0]["unrealized_gain_loss"] is None


def test_lot_with_confirmed_close_has_market_value_and_unrealized_gain(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    today = _today_market_date()
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security_id = _seed_security(session, symbol="MKTVAL")
        lot = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-mktval",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        _seed_daily_close(
            session, security_id=security_id, market_date=today, close_price=Price("110.00")
        )
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    lots = response.get_json()["lots"]
    assert len(lots) == 1
    lot_json = lots[0]
    assert lot_json["id"] == str(lot.id)
    # 10 units x $110.000000 close = $1100.0000 market value, minus $1000.0000 basis = $100.0000.
    assert lot_json["current_price"] == "110.000000"
    assert lot_json["market_value"] == "1100.0000"
    assert lot_json["unrealized_gain_loss"] == "100.0000"


def test_closed_lot_has_null_market_value_even_with_a_confirmed_close(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    today = _today_market_date()
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security_id = _seed_security(session, symbol="CLOSEDLOT")
        lot = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-closed",
            quantity_opened=Units("10"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        _seed_daily_close(
            session, security_id=security_id, market_date=today, close_price=Price("110.00")
        )
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    lots = response.get_json()["lots"]
    assert len(lots) == 1
    lot_json = lots[0]
    assert lot_json["id"] == str(lot.id)
    assert lot_json["current_price"] is None
    assert lot_json["market_value"] is None
    assert lot_json["unrealized_gain_loss"] is None


def test_lot_wash_sale_disallowed_sums_multiple_adjustments(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security_id = _seed_security(session, symbol="WASHSUM")
        replacement_lot = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-replacement",
            quantity_opened=Units("10"),
            quantity_remaining=Units("10"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1050.00"),
        )
        sold_lot_1 = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-sold-1",
            quantity_opened=Units("5"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("500.00"),
            adjusted_basis=Money("500.00"),
        )
        sold_lot_2 = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-sold-2",
            quantity_opened=Units("5"),
            quantity_remaining=Units("0"),
            original_cost_basis=Money("500.00"),
            adjusted_basis=Money("500.00"),
        )
        consumption_1 = _seed_lot_consumption(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            tax_lot_id=sold_lot_1.id,
            execution_id="sell-1",
            quantity_consumed=Units("5"),
            realized_gain_loss=Money("-30.00"),
            sale_date=date(2026, 1, 4),
        )
        consumption_2 = _seed_lot_consumption(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            tax_lot_id=sold_lot_2.id,
            execution_id="sell-2",
            quantity_consumed=Units("5"),
            realized_gain_loss=Money("-20.00"),
            sale_date=date(2026, 1, 4),
        )
        _seed_wash_sale_adjustment(
            session,
            original_lot_consumption_id=consumption_1.id,
            replacement_tax_lot_id=replacement_lot.id,
            disallowed_amount=Money("30.00"),
            effective_date=date(2026, 1, 5),
        )
        _seed_wash_sale_adjustment(
            session,
            original_lot_consumption_id=consumption_2.id,
            replacement_tax_lot_id=replacement_lot.id,
            disallowed_amount=Money("20.00"),
            effective_date=date(2026, 1, 5),
        )
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    lots = {entry["id"]: entry for entry in response.get_json()["lots"]}
    assert lots[str(replacement_lot.id)]["wash_sale_disallowed"] == "50.0000"


def test_lot_consumptions_ordered_most_recent_sale_first(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        security_id = _seed_security(session, symbol="ORDERED")
        lot = _seed_open_lot(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            execution_id="buy-ordered",
            quantity_opened=Units("10"),
            quantity_remaining=Units("4"),
            original_cost_basis=Money("1000.00"),
            adjusted_basis=Money("1000.00"),
        )
        earlier = _seed_lot_consumption(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            tax_lot_id=lot.id,
            execution_id="sell-earlier",
            quantity_consumed=Units("3"),
            realized_gain_loss=Money("10.00"),
            sale_date=date(2026, 1, 6),
        )
        later = _seed_lot_consumption(
            session,
            customer_id=uuid.UUID(customer_id),
            security_id=security_id,
            tax_lot_id=lot.id,
            execution_id="sell-later",
            quantity_consumed=Units("3"),
            realized_gain_loss=Money("20.00"),
            sale_date=date(2026, 1, 10),
        )
        session.commit()
    finally:
        session.close()

    response = api_client.get("/api/v1/lots")

    assert response.status_code == 200
    lots = {entry["id"]: entry for entry in response.get_json()["lots"]}
    consumption_ids = [c["id"] for c in lots[str(lot.id)]["consumptions"]]
    assert consumption_ids == [str(later.id), str(earlier.id)]


def test_is_throttled(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/lots")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
