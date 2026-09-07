"""`GET /api/v1/portfolios/performance` (ADR 26) via the Flask test client -- folds stored
`sub_period_return` rows into an ordered `[{date, value}]` series plus a cumulative TWR. Always the
live series; `tests/api/test_statements_api.py` covers the as-published counterpart separately.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.clock import MARKET_TIMEZONE
from app.core.money import Money
from app.models.marketdata.sub_period_return import SubPeriodReturn

CUSTOMER_EMAIL = "performance-customer@trueup.example"
CUSTOMER_EMAIL_2 = "performance-customer-2@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
TODAY = datetime.now(UTC).astimezone(MARKET_TIMEZONE).date()
"""Matches `MarketClock.market_date()`'s own computation; the controller has no injectable clock."""

PERFORMANCE_TABLES = [SubPeriodReturn.__table__]


@pytest.fixture(autouse=True)
def _performance_tables(owner_engine: Engine) -> Iterator[None]:
    for table in PERFORMANCE_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(PERFORMANCE_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))


def _register(client: FlaskClient, *, email: str, password: str) -> uuid.UUID:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return uuid.UUID(response.get_json()["id"])


def _login(client: FlaskClient, *, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    csrf_token: str = response.get_json()["csrf_token"]
    return csrf_token


def _recent_sub_period(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    """One row inside every allowlisted range: `[today - 10d, today]`, +5% return."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        SubPeriodReturn(
            customer_id=customer_id,
            sub_period_start=TODAY - timedelta(days=10),
            sub_period_end=TODAY,
            return_pct=Decimal("0.0500000000"),
            value_begin=Money("10000.0000"),
            value_end=Money("10500.0000"),
            flow_amount=Money("0.0000"),
            is_provisional=False,
        )
    )
    session.commit()
    session.close()


def _old_sub_period(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    """A second row well outside every range but `all`: `[today - 200d, today - 190d]`."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        SubPeriodReturn(
            customer_id=customer_id,
            sub_period_start=TODAY - timedelta(days=200),
            sub_period_end=TODAY - timedelta(days=190),
            return_pct=Decimal("0.0200000000"),
            value_begin=Money("9000.0000"),
            value_end=Money("9180.0000"),
            flow_amount=Money("0.0000"),
            is_provisional=False,
        )
    )
    session.commit()
    session.close()


# --- GET /portfolios/performance -------------------------------------------------------------


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/portfolios/performance")

    assert response.status_code == 401


def test_default_range_folds_the_stored_sub_period_into_points(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _recent_sub_period(owner_engine, customer_id)

    response = api_client.get("/api/v1/portfolios/performance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["customer_id"] == str(customer_id)
    assert body["range"] == "1m"
    assert body["period_start"] == (TODAY - timedelta(days=10)).isoformat()
    assert body["period_end"] == TODAY.isoformat()
    assert body["cumulative_twr"] == "0.0500000000"
    assert body["is_provisional"] is False
    assert body["watermark_type"] == "live"
    assert body["points"] == [
        {"as_of_date": (TODAY - timedelta(days=10)).isoformat(), "value": "10000.0000"},
        {"as_of_date": TODAY.isoformat(), "value": "10500.0000"},
    ]


def test_1m_range_excludes_a_sub_period_outside_the_window(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _recent_sub_period(owner_engine, customer_id)
    _old_sub_period(owner_engine, customer_id)

    response = api_client.get("/api/v1/portfolios/performance?range=1m")

    assert response.status_code == 200
    body = response.get_json()
    assert body["period_start"] == (TODAY - timedelta(days=10)).isoformat()
    assert body["cumulative_twr"] == "0.0500000000"
    assert len(body["points"]) == 2


def test_all_range_includes_every_stored_sub_period(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _recent_sub_period(owner_engine, customer_id)
    _old_sub_period(owner_engine, customer_id)

    response = api_client.get("/api/v1/portfolios/performance?range=all")

    assert response.status_code == 200
    body = response.get_json()
    assert body["period_start"] == (TODAY - timedelta(days=200)).isoformat()
    # (1.02 * 1.05) - 1, quantized to sub_period_return.return_pct's NUMERIC(18,10) scale.
    assert body["cumulative_twr"] == "0.0710000000"
    assert body["points"] == [
        {"as_of_date": (TODAY - timedelta(days=200)).isoformat(), "value": "9000.0000"},
        {"as_of_date": (TODAY - timedelta(days=190)).isoformat(), "value": "9180.0000"},
        {"as_of_date": TODAY.isoformat(), "value": "10500.0000"},
    ]


def test_no_stored_coverage_is_an_empty_series_not_an_error(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/performance?range=1y")

    assert response.status_code == 200
    body = response.get_json()
    assert body["period_start"] is None
    assert body["cumulative_twr"] == "0.0000000000"
    assert body["points"] == []


def test_invalid_range_is_a_validation_error(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/performance?range=2y")

    assert response.status_code == 422
    assert response.get_json()["code"] == "invalid_range"


def test_another_customers_performance_is_isolated(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _recent_sub_period(owner_engine, customer_id)

    _register(api_client, email=CUSTOMER_EMAIL_2, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL_2, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/performance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["points"] == []
    assert body["cumulative_twr"] == "0.0000000000"


def test_is_throttled(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/portfolios/performance")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
