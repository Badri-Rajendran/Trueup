"""`GET /api/v1/portfolios/models`, `GET, POST /api/v1/portfolios/assignment` (S8 §3, S9 §3) via
the Flask test client.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.clock import MARKET_TIMEZONE
from app.models.identity.staff import Staff, StaffRole
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.identity.auth import hash_password

CUSTOMER_EMAIL = "portfolios-customer@trueup.example"
CUSTOMER_EMAIL_2 = "portfolios-customer-2@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "portfolios-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"

PORTFOLIO_TABLES = [
    Security.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
    CustomerModelAssignment.__table__,
]


@pytest.fixture(autouse=True)
def _portfolio_tables(owner_engine: Engine) -> Iterator[None]:
    for table in PORTFOLIO_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(PORTFOLIO_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))


def _seed_active_model(
    owner_engine: Engine, *, name: str = "Growth", is_active: bool = True
) -> tuple[uuid.UUID, uuid.UUID, str]:
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        symbol = f"S{uuid.uuid4().hex[:9].upper()}"
        security = Security(
            symbol=symbol, name="Growth Co.", asset_class=SecurityAssetClass.EQUITY
        )
        session.add(security)
        session.flush()
        model = ModelPortfolio(name=name, is_active=is_active)
        session.add(model)
        session.flush()
        session.add(
            TargetWeight(
                model_portfolio_id=model.id,
                security_id=security.id,
                weight_pct=Decimal("1.0000"),
            )
        )
        session.commit()
        return model.id, security.id, symbol
    finally:
        session.close()


def _register(client: FlaskClient, *, email: str, password: str) -> uuid.UUID:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return uuid.UUID(response.get_json()["id"])


def _login(client: FlaskClient, *, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    csrf_token: str = response.get_json()["csrf_token"]
    return csrf_token


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


def _staff_login_with_mfa(client: FlaskClient) -> str:
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
    return pending_csrf


# --- GET /portfolios/models -----------------------------------------------------------------


def test_list_models_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/portfolios/models")

    assert response.status_code == 401


def test_list_models_returns_active_models_with_target_weights(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    model_id, security_id, symbol = _seed_active_model(owner_engine)
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/models")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["models"]) == 1
    model = body["models"][0]
    assert model["id"] == str(model_id)
    assert model["name"] == "Growth"
    assert model["target_weights"] == [
        {"security_id": str(security_id), "symbol": symbol, "weight_pct": "1.0000"}
    ]


def test_list_models_excludes_inactive_models(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _seed_active_model(owner_engine, name="Retired", is_active=False)
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/models")

    assert response.status_code == 200
    assert response.get_json()["models"] == []


def test_list_models_is_throttled(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/portfolios/models")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /portfolios/assignment -------------------------------------------------------------


def test_get_assignment_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/portfolios/assignment")

    assert response.status_code == 401


def test_get_assignment_returns_none_when_unassigned(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/assignment")

    assert response.status_code == 200
    assert response.get_json()["assignment"] is None


def test_staff_get_assignment_without_customer_id_is_a_validation_error(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    _staff_login_with_mfa(api_client)

    response = api_client.get("/api/v1/portfolios/assignment")

    assert response.status_code == 422


def test_staff_get_assignment_with_customer_id_sees_that_customers_assignment(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    model_id, _, _symbol = _seed_active_model(owner_engine)
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id), "model_portfolio_id": str(model_id)},
        headers={"X-CSRFToken": csrf_token},
    )
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    _staff_login_with_mfa(api_client)
    response = api_client.get(f"/api/v1/portfolios/assignment?customer_id={customer_id}")

    assert response.status_code == 200
    assert response.get_json()["assignment"]["model_portfolio_id"] == str(model_id)


# --- POST /portfolios/assignment ------------------------------------------------------------


def test_create_assignment_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(uuid.uuid4()), "model_portfolio_id": str(uuid.uuid4())},
    )

    assert response.status_code == 400  # CSRFProtect rejects first, matching auth.py's precedent


def test_create_assignment_happy_path_and_reassignment_overwrites(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    first_model_id, _, _s1 = _seed_active_model(owner_engine, name="Growth")
    second_model_id, _, _s2 = _seed_active_model(owner_engine, name="Conservative")
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    first = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id), "model_portfolio_id": str(first_model_id)},
        headers={"X-CSRFToken": csrf_token},
    )
    assert first.status_code == 201
    assert first.get_json()["model_portfolio_id"] == str(first_model_id)
    expected_market_date = datetime.now(UTC).astimezone(MARKET_TIMEZONE).date()
    assert first.get_json()["assigned_at"] == expected_market_date.isoformat()

    second = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id), "model_portfolio_id": str(second_model_id)},
        headers={"X-CSRFToken": csrf_token},
    )
    assert second.status_code == 201
    assert second.get_json()["model_portfolio_id"] == str(second_model_id)

    current = api_client.get("/api/v1/portfolios/assignment")
    assert current.get_json()["assignment"]["model_portfolio_id"] == str(second_model_id)


def test_create_assignment_rejects_a_customer_acting_on_anothers_behalf(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    model_id, _, _symbol = _seed_active_model(owner_engine)
    other_customer_id = _register(api_client, email=CUSTOMER_EMAIL_2, password=CUSTOMER_PASSWORD)
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(other_customer_id), "model_portfolio_id": str(model_id)},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 403


def test_create_assignment_rejects_a_missing_model_portfolio_id(api_client: FlaskClient) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id)},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422


def test_create_assignment_rejects_an_unknown_model_portfolio(api_client: FlaskClient) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id), "model_portfolio_id": str(uuid.uuid4())},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "model_portfolio_not_found"


def test_create_assignment_rejects_an_inactive_model_portfolio(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    inactive_model_id, _, _s3 = _seed_active_model(owner_engine, name="Retired", is_active=False)
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.post(
        "/api/v1/portfolios/assignment",
        json={"customer_id": str(customer_id), "model_portfolio_id": str(inactive_model_id)},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "model_portfolio_not_found"


def test_create_assignment_is_throttled(api_client: FlaskClient, owner_engine: Engine) -> None:
    model_id, _, _symbol = _seed_active_model(owner_engine)
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            "/api/v1/portfolios/assignment",
            json={"customer_id": str(customer_id), "model_portfolio_id": str(model_id)},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
