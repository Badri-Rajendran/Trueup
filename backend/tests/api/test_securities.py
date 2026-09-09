"""`GET /api/v1/securities` via the Flask test client: authn (any session, not customer-only),
the response shape, `source`/`status` provenance pass-through (`SimulatedBadge`'s exact input),
and pagination round-trip.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.money import Price
from app.models.identity.staff import Staff, StaffRole
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass, SecurityStatus
from app.services.identity.auth import hash_password

CUSTOMER_EMAIL = "securities-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "securities-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"

_TABLES = [Security.__table__, DailyClose.__table__]


@pytest.fixture(autouse=True)
def _securities_tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _register_and_login(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL, password: str = CUSTOMER_PASSWORD
) -> str:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_response.status_code == 200
    csrf_token: str = login_response.get_json()["csrf_token"]
    return csrf_token


def _insert_security(
    owner_engine: Engine, *, symbol: str, status: SecurityStatus = SecurityStatus.ACTIVE
) -> Security:
    session = Session(bind=owner_engine, expire_on_commit=False)
    security = Security(
        symbol=symbol, name=f"{symbol} Co", asset_class=SecurityAssetClass.EQUITY, status=status
    )
    session.add(security)
    session.commit()
    session.close()
    return security


def _insert_close(
    owner_engine: Engine,
    *,
    security_id: object,
    market_date: date,
    recorded_at: datetime,
    price: str = "100.00",
    source: MarketDataSource = MarketDataSource.LIVE,
    status: DailyCloseStatus = DailyCloseStatus.CONFIRMED,
) -> DailyClose:
    session = Session(bind=owner_engine, expire_on_commit=False)
    close = DailyClose(
        security_id=security_id,
        market_date=market_date,
        close_price=Price(price),
        source=source,
        status=status,
        recorded_at=recorded_at,
    )
    session.add(close)
    session.commit()
    session.close()
    return close


# --- authentication --------------------------------------------------------------------------


def test_list_securities_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/securities")

    assert response.status_code == 401


def test_list_securities_accessible_to_a_staff_session(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """Not tenant-scoped: a staff session may read it too, with no `customer_id` to supply."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        Staff(
            email=STAFF_EMAIL,
            password_hash=hash_password(STAFF_PASSWORD),
            role=StaffRole.adviser,
        )
    )
    session.commit()
    session.close()

    login_response = api_client.post(
        "/api/v1/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD}
    )
    assert login_response.status_code == 200
    pending_csrf = login_response.get_json()["csrf_token"]
    secret = api_client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": pending_csrf}
    ).get_json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": pending_csrf}
    )
    assert verify.status_code == 200

    response = api_client.get("/api/v1/securities")

    assert response.status_code == 200
    assert response.get_json() == {"securities": [], "next_cursor": None}


# --- happy path / response shape ---------------------------------------------------------------


def test_list_securities_happy_path_with_a_live_close(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register_and_login(api_client)
    security = _insert_security(owner_engine, symbol="AAPL")
    _insert_close(
        owner_engine,
        security_id=security.id,
        market_date=date(2026, 1, 10),
        recorded_at=datetime(2026, 1, 10, 21, 0, tzinfo=UTC),
        price="150.25",
    )

    response = api_client.get("/api/v1/securities")

    assert response.status_code == 200
    assert response.get_json() == {
        "securities": [
            {
                "security_id": str(security.id),
                "symbol": "AAPL",
                "name": "AAPL Co",
                "asset_class": "equity",
                "last_close": {
                    "price": "150.250000",
                    "market_date": "2026-01-10",
                    "source": "live",
                    "status": "confirmed",
                },
            }
        ],
        "next_cursor": None,
    }


def test_list_securities_happy_path_with_no_close_is_null(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register_and_login(api_client)
    security = _insert_security(owner_engine, symbol="ZZZ")

    response = api_client.get("/api/v1/securities")

    assert response.status_code == 200
    assert response.get_json() == {
        "securities": [
            {
                "security_id": str(security.id),
                "symbol": "ZZZ",
                "name": "ZZZ Co",
                "asset_class": "equity",
                "last_close": None,
            }
        ],
        "next_cursor": None,
    }


def test_list_securities_simulated_source_passes_through_untouched(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register_and_login(api_client)
    security = _insert_security(owner_engine, symbol="SIMU")
    _insert_close(
        owner_engine,
        security_id=security.id,
        market_date=date(2026, 1, 10),
        recorded_at=datetime(2026, 1, 10, 21, 0, tzinfo=UTC),
        source=MarketDataSource.SIMULATED,
    )

    response = api_client.get("/api/v1/securities")

    assert response.status_code == 200
    body = response.get_json()
    assert body["securities"][0]["last_close"]["source"] == "simulated"


def test_list_securities_never_includes_an_inactive_security(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register_and_login(api_client)
    _insert_security(owner_engine, symbol="DELISTED", status=SecurityStatus.INACTIVE)

    response = api_client.get("/api/v1/securities")

    assert response.status_code == 200
    assert response.get_json() == {"securities": [], "next_cursor": None}


# --- pagination --------------------------------------------------------------------------------


def test_list_securities_pagination_round_trip(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register_and_login(api_client)
    for symbol in ("AAA", "BBB", "CCC"):
        _insert_security(owner_engine, symbol=symbol)

    first = api_client.get("/api/v1/securities", query_string={"limit": 2})
    assert first.status_code == 200
    first_body = first.get_json()
    assert [s["symbol"] for s in first_body["securities"]] == ["AAA", "BBB"]
    assert first_body["next_cursor"] is not None

    second = api_client.get(
        "/api/v1/securities", query_string={"limit": 2, "after": first_body["next_cursor"]}
    )
    assert second.status_code == 200
    second_body = second.get_json()
    assert [s["symbol"] for s in second_body["securities"]] == ["CCC"]
    assert second_body["next_cursor"] is None


# --- validation boundaries -----------------------------------------------------------------------


def test_list_securities_rejects_limit_over_the_maximum(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    response = api_client.get("/api/v1/securities", query_string={"limit": 201})

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"
