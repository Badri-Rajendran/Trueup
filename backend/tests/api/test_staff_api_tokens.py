"""`app/controllers/admin/staff_api_tokens.py` (S13 §3.2) via the Flask test client: issue/list/
revoke, self-service enforcement, validation, authn/authz, and throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.models.identity.staff import Staff, StaffRole
from app.models.identity.staff_api_token import StaffApiToken
from app.models.ops.admin_audit_log import AdminAuditLog
from app.services.identity.auth import hash_password

STAFF_EMAIL = "token-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"
OTHER_STAFF_EMAIL = "token-other-adviser@trueup.example"

# Staff/Customer are owned by tests/api/conftest.py's session-scoped fixture, not here.
_TABLES = [StaffApiToken.__table__, AdminAuditLog.__table__]


@pytest.fixture(autouse=True)
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


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


@pytest.fixture
def other_staff_member(owner_engine: Engine) -> Iterator[Staff]:
    session = Session(bind=owner_engine, expire_on_commit=False)
    staff = Staff(
        email=OTHER_STAFF_EMAIL,
        password_hash=hash_password("irrelevant-password"),
        role=StaffRole.adviser,
    )
    session.add(staff)
    session.commit()
    yield staff
    session.close()


def _staff_login_with_mfa(
    client: FlaskClient, *, email: str = STAFF_EMAIL, password: str = STAFF_PASSWORD
) -> str:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
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


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/admin/staff-api-tokens")

    assert response.status_code == 401


def test_issue_requires_a_non_empty_label(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.post(
        "/api/v1/admin/staff-api-tokens", json={}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422


def test_issue_returns_the_raw_token_exactly_once(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.post(
        "/api/v1/admin/staff-api-tokens",
        json={"label": "ops laptop MCP client"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["label"] == "ops laptop MCP client"
    assert len(body["token"]) > 20

    list_response = api_client.get(
        "/api/v1/admin/staff-api-tokens", headers={"X-CSRFToken": csrf_token}
    )
    assert list_response.status_code == 200
    tokens = list_response.get_json()["tokens"]
    assert len(tokens) == 1
    assert "token" not in tokens[0]
    assert "token_hash" not in tokens[0]


def test_revoke_marks_the_token_revoked(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    issued = api_client.post(
        "/api/v1/admin/staff-api-tokens",
        json={"label": "a token"},
        headers={"X-CSRFToken": csrf_token},
    ).get_json()

    response = api_client.delete(
        f"/api/v1/admin/staff-api-tokens/{issued['id']}", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 200
    assert response.get_json()["revoked_at"] is not None


def test_revoking_an_unknown_token_returns_404(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.delete(
        f"/api/v1/admin/staff-api-tokens/{uuid.uuid4()}", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 404


def test_cannot_revoke_another_staff_members_token(
    api_client: FlaskClient, staff_member: Staff, other_staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    issued = api_client.post(
        "/api/v1/admin/staff-api-tokens",
        json={"label": "adviser's own token"},
        headers={"X-CSRFToken": csrf_token},
    ).get_json()
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    other_csrf_token = _staff_login_with_mfa(
        api_client, email=OTHER_STAFF_EMAIL, password="irrelevant-password"
    )

    response = api_client.delete(
        f"/api/v1/admin/staff-api-tokens/{issued['id']}", headers={"X-CSRFToken": other_csrf_token}
    )

    assert response.status_code == 403


def test_issue_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            "/api/v1/admin/staff-api-tokens",
            json={"label": "spam"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
