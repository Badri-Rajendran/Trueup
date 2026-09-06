"""`POST /api/v1/admin/kyc-overrides/<customer_id>` (S8 §4 row 5) via the Flask test client:
reopening a locked-rejected KYC status, validation, authz, and throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.models.identity.customer import Customer, KycStatus
from app.models.identity.kyc_session import KycSession
from app.models.identity.staff import Staff, StaffRole
from app.models.ops.admin_audit_log import AdminAuditLog
from app.services.identity.auth import hash_password

CUSTOMER_EMAIL = "kyc-override-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "kyc-override-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"

OVERRIDE_TABLES = [KycSession.__table__, AdminAuditLog.__table__]


@pytest.fixture(autouse=True)
def _override_tables(owner_engine: Engine) -> Iterator[None]:
    for table in OVERRIDE_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(OVERRIDE_TABLES):
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

    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


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
    csrf_token: str = verify.get_json()["csrf_token"]
    return csrf_token


def _lock_out(
    owner_engine: Engine, customer_id: str, *, api_client: FlaskClient, csrf_token: str
) -> None:
    first = api_client.post(
        "/api/v1/identity/kyc-sessions",
        json={"customer_id": customer_id},
        headers={"X-CSRFToken": csrf_token},
    )
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


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.post(f"/api/v1/admin/kyc-overrides/{uuid.uuid4()}")

    assert response.status_code == 400  # CSRFProtect rejects an unauthenticated POST first.


def test_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        f"/api/v1/admin/kyc-overrides/{uuid.uuid4()}",
        json={"reason": "manual review"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 403


def test_missing_reason_is_rejected(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.post(
        f"/api/v1/admin/kyc-overrides/{uuid.uuid4()}",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422


def test_unknown_customer_returns_404(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.post(
        f"/api/v1/admin/kyc-overrides/{uuid.uuid4()}",
        json={"reason": "manual review"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 404


def test_override_reopens_a_locked_customer_for_a_fresh_attempt(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id, customer_csrf = _register_and_login(api_client)
    _lock_out(owner_engine, customer_id, api_client=api_client, csrf_token=customer_csrf)
    locked_again = api_client.post(
        "/api/v1/identity/kyc-sessions",
        json={"customer_id": customer_id},
        headers={"X-CSRFToken": customer_csrf},
    )
    assert locked_again.status_code == 422
    assert locked_again.get_json()["code"] == "kyc_locked"
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": customer_csrf})

    staff_csrf = _staff_login_with_mfa(api_client)
    override_response = api_client.post(
        f"/api/v1/admin/kyc-overrides/{customer_id}",
        json={"reason": "customer called support, ID confirmed manually"},
        headers={"X-CSRFToken": staff_csrf},
    )

    assert override_response.status_code == 200
    assert override_response.get_json()["kyc_status"] == "pending"

    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": staff_csrf})
    relogin = api_client.post(
        "/api/v1/auth/login", json={"email": CUSTOMER_EMAIL, "password": CUSTOMER_PASSWORD}
    )
    assert relogin.status_code == 200
    customer_csrf_2 = relogin.get_json()["csrf_token"]
    retry = api_client.post(
        "/api/v1/identity/kyc-sessions",
        json={"customer_id": customer_id},
        headers={"X-CSRFToken": customer_csrf_2},
    )
    assert retry.status_code == 201


def test_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            f"/api/v1/admin/kyc-overrides/{uuid.uuid4()}",
            json={"reason": "manual review"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
