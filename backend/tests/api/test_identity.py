"""`POST /api/v1/identity/kyc-sessions`, `GET /api/v1/identity/status/<customer_id>` (S2 §6) via
the Flask test client: happy path, validation, authn/authz/ownership, throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from werkzeug.test import TestResponse

from app.config import get_settings
from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.models.identity.customer import Customer, KycStatus
from app.models.identity.kyc_session import KycSession
from app.models.ledger.account import Account
from app.models.ledger.customer_cash_lock import CustomerCashLock

CUSTOMER_EMAIL = "identity-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
OTHER_EMAIL = "identity-other@trueup.example"

# `Account`/`CustomerCashLock` are needed only once a verdict reaches AccountApprovalService's
# ledger-provisioning step (the self-heal tests below); listed alongside `KycSession` so every
# test in this file shares one table lifecycle, matching `test_funding.py`'s convention.
_TABLES = [KycSession.__table__, Account.__table__, CustomerCashLock.__table__]


@pytest.fixture(autouse=True)
def _kyc_session_table(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture(autouse=True)
def _fake_kyc_port(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.controllers.api.identity as identity_controller

    monkeypatch.setattr(identity_controller, "_build_kyc_port", lambda: FakeKycAdapter())


def _register_and_login(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL, password: str = CUSTOMER_PASSWORD
) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _start_kyc_session(
    client: FlaskClient, *, customer_id: str, csrf_token: str
) -> TestResponse:
    return client.post(
        "/api/v1/identity/kyc-sessions",
        json={"customer_id": customer_id},
        headers={"X-CSRFToken": csrf_token},
    )


# --- POST /kyc-sessions --------------------------------------------------------------------


def test_start_kyc_session_happy_path(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    response = _start_kyc_session(api_client, customer_id=customer_id, csrf_token=csrf_token)

    assert response.status_code == 201
    body = response.get_json()
    assert body["provider_session_id"]
    assert body["client_secret"]


def test_start_kyc_session_rejects_missing_customer_id(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/identity/kyc-sessions", json={}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_start_kyc_session_rejects_an_unauthenticated_request(api_client: FlaskClient) -> None:
    response = api_client.post(
        "/api/v1/identity/kyc-sessions", json={"customer_id": "not-even-checked-yet"}
    )
    assert response.status_code == 400  # CSRFProtect rejects first, matching auth.py's own tests.


def test_start_kyc_session_rejects_another_customers_id(api_client: FlaskClient) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _, csrf_token = _register_and_login(api_client)

    response = _start_kyc_session(api_client, customer_id=other_id, csrf_token=csrf_token)

    assert response.status_code == 403


def test_start_kyc_session_is_blocked_once_locked_rejected(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """S2 §9/S8 §6 case 3: exhausted attempts lock kyc_status to rejected; only an adviser
    override can reopen."""
    customer_id, csrf_token = _register_and_login(api_client)
    first = _start_kyc_session(api_client, customer_id=customer_id, csrf_token=csrf_token)
    assert first.status_code == 201

    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        kyc_session = (
            session.query(KycSession).filter_by(customer_id=uuid.UUID(customer_id)).one()
        )
        kyc_session.attempt_number = get_settings().kyc_max_attempts
        customer = session.get(Customer, uuid.UUID(customer_id))
        assert customer is not None
        customer.kyc_status = KycStatus.rejected
        session.commit()
    finally:
        session.close()

    response = _start_kyc_session(api_client, customer_id=customer_id, csrf_token=csrf_token)

    assert response.status_code == 422
    assert response.get_json()["code"] == "kyc_locked"


def test_start_kyc_session_is_throttled(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    last_response = None
    for _ in range(6):
        last_response = _start_kyc_session(
            api_client, customer_id=customer_id, csrf_token=csrf_token
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /status/<customer_id> ----------------------------------------------------------------


def test_get_identity_status_happy_path(api_client: FlaskClient) -> None:
    customer_id, _csrf_token = _register_and_login(api_client)

    response = api_client.get(f"/api/v1/identity/status/{customer_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body == {"kyc_status": "pending", "account_approval_status": "pending"}


def test_get_identity_status_rejects_an_unauthenticated_request(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    response = api_client.get(f"/api/v1/identity/status/{customer_id}")

    assert response.status_code == 401


def test_get_identity_status_rejects_another_customers_id(api_client: FlaskClient) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _register_and_login(api_client)

    response = api_client.get(f"/api/v1/identity/status/{other_id}")

    assert response.status_code == 403


def test_get_identity_status_self_heals_when_the_verdict_webhook_never_arrives(
    api_client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact local-dev scenario this exists for: Stripe can't reach `localhost` to deliver
    `identity.verification_session.verified`, so no webhook ever lands -- the status endpoint must
    still resolve by asking the provider directly, with no webhook involved at all."""
    import app.controllers.api.identity as identity_controller

    shared_port = FakeKycAdapter()
    monkeypatch.setattr(identity_controller, "_build_kyc_port", lambda: shared_port)

    customer_id, csrf_token = _register_and_login(api_client)
    started = _start_kyc_session(api_client, customer_id=customer_id, csrf_token=csrf_token)
    assert started.status_code == 201
    provider_session_id = started.get_json()["provider_session_id"]

    pending_response = api_client.get(f"/api/v1/identity/status/{customer_id}")
    assert pending_response.get_json()["kyc_status"] == "pending"

    shared_port.retrieved_statuses[provider_session_id] = "verified"

    response = api_client.get(f"/api/v1/identity/status/{customer_id}")

    assert response.status_code == 200
    assert response.get_json()["kyc_status"] == "approved"


def test_get_identity_status_does_not_repoll_once_already_resolved(
    api_client: FlaskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.controllers.api.identity as identity_controller

    shared_port = FakeKycAdapter()
    monkeypatch.setattr(identity_controller, "_build_kyc_port", lambda: shared_port)

    customer_id, csrf_token = _register_and_login(api_client)
    started = _start_kyc_session(api_client, customer_id=customer_id, csrf_token=csrf_token)
    provider_session_id = started.get_json()["provider_session_id"]
    shared_port.retrieved_statuses[provider_session_id] = "verified"
    first = api_client.get(f"/api/v1/identity/status/{customer_id}")
    assert first.get_json()["kyc_status"] == "approved"

    # If this second call polled the provider again, a "canceled" status would flip the customer
    # to rejected -- it must not, since kyc_session already transitioned exactly once.
    shared_port.retrieved_statuses[provider_session_id] = "canceled"

    response = api_client.get(f"/api/v1/identity/status/{customer_id}")

    assert response.get_json()["kyc_status"] == "approved"
