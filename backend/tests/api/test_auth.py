"""`POST /api/v1/auth/*` (S0 §7.1/§7.2) via the Flask test client. `register`/`login` are
CSRF-exempt; every route after requires the `csrf_token` as `X-CSRFToken`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine
from werkzeug.test import TestResponse

from app.models.identity.staff import Staff, StaffRole
from app.services.identity.auth import generate_totp_secret, hash_password

CUSTOMER_EMAIL = "customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"


@pytest.fixture
def staff_member(owner_engine: Engine) -> Iterator[Staff]:
    from sqlalchemy.orm import Session

    session = Session(bind=owner_engine, expire_on_commit=False)
    staff = Staff(
        email=STAFF_EMAIL,
        password_hash=hash_password(STAFF_PASSWORD),
        role=StaffRole.adviser,
    )
    session.add(staff)
    session.commit()
    yield staff
    session.close()


@pytest.fixture
def enrolled_staff_member(owner_engine: Engine) -> Iterator[Staff]:
    """A staff member with MFA already enrolled, for F3's re-enrollment-bypass tests."""
    from sqlalchemy.orm import Session

    session = Session(bind=owner_engine, expire_on_commit=False)
    staff = Staff(
        email=STAFF_EMAIL,
        password_hash=hash_password(STAFF_PASSWORD),
        role=StaffRole.adviser,
        totp_secret_encrypted=generate_totp_secret(),
    )
    session.add(staff)
    session.commit()
    yield staff
    session.close()


def _register(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL, password: str = CUSTOMER_PASSWORD
) -> TestResponse:
    return client.post("/api/v1/auth/register", json={"email": email, "password": password})


def _login(client: FlaskClient, *, email: str, password: str) -> TestResponse:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


# --- register ----------------------------------------------------------------------------------


def test_register_happy_path_creates_a_customer(api_client: FlaskClient) -> None:
    response = _register(api_client)

    assert response.status_code == 201
    body = response.get_json()
    assert body["email"] == CUSTOMER_EMAIL
    assert "id" in body
    assert "created_at" in body
    assert "password" not in body
    assert "password_hash" not in body


def test_register_rejects_a_duplicate_email(api_client: FlaskClient) -> None:
    first = _register(api_client)
    assert first.status_code == 201

    second = _register(api_client)

    assert second.status_code == 422
    assert second.get_json()["code"] == "validation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": "a-fine-password"},
        {"email": "missing-password@trueup.example"},
        {"email": "short-password@trueup.example", "password": "short"},
        {},
    ],
)
def test_register_rejects_invalid_input(api_client: FlaskClient, payload: dict[str, str]) -> None:
    response = api_client.post("/api/v1/auth/register", json=payload)

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


# --- login: customer -----------------------------------------------------------------------


def test_login_customer_happy_path(api_client: FlaskClient) -> None:
    assert _register(api_client).status_code == 201

    response = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    assert response.status_code == 200
    body = response.get_json()
    assert body["email"] == CUSTOMER_EMAIL
    assert body["role"] == "customer"
    assert body["mfa_pending"] is False
    assert body["csrf_token"]


def test_login_sets_a_session_cookie(api_client: FlaskClient) -> None:
    assert _register(api_client).status_code == 201

    response = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    assert response.status_code == 200
    assert api_client.get_cookie("session") is not None


# --- login: staff lands in the pending-MFA state --------------------------------------------


def test_login_staff_happy_path_lands_in_pending_mfa(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "mfa_required"
    assert body["mfa_pending"] is True
    assert body["csrf_token"]
    # No TOTP secret yet, so the client must be told to enroll rather than shown a code box it
    # cannot satisfy -- `/mfa/verify` would reject this account with 403 "MFA not enrolled".
    assert body["mfa_enrolled"] is False
    # The pending state must not be a completed login: no full AuthResponse fields.
    assert "role" not in body


def test_login_staff_already_enrolled_reports_mfa_enrolled(
    api_client: FlaskClient, enrolled_staff_member: Staff
) -> None:
    """The other branch of the same flag: this account goes straight to code entry."""
    response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "mfa_required"
    assert body["mfa_enrolled"] is True


# --- login: indistinguishable failure shape --------------------------------------------------


def test_login_wrong_password_and_unknown_email_return_the_same_shape(
    api_client: FlaskClient,
) -> None:
    assert _register(api_client).status_code == 201

    wrong_password = _login(api_client, email=CUSTOMER_EMAIL, password="not-the-right-password")
    unknown_email = _login(
        api_client, email="nobody-here@trueup.example", password="whatever-12345"
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    # Same shape everywhere except correlation_id (S0 §7 login test list).
    wrong_password_body = wrong_password.get_json()
    unknown_email_body = unknown_email.get_json()
    del wrong_password_body["correlation_id"]
    del unknown_email_body["correlation_id"]
    assert wrong_password_body == unknown_email_body


# --- logout ----------------------------------------------------------------------------------


def test_logout_clears_the_session(api_client: FlaskClient) -> None:
    assert _register(api_client).status_code == 201
    login_response = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]

    response = api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 200
    assert response.get_json()["status"] == "logged_out"


# --- mfa/enroll + mfa/verify (staff only) ----------------------------------------------------


def test_mfa_enroll_with_no_session_at_all_is_rejected(api_client: FlaskClient) -> None:
    """No cookie, no CSRF token — CSRFProtect rejects before the view runs (S0 §8)."""
    response = api_client.post("/api/v1/auth/mfa/enroll")
    assert response.status_code == 400
    assert response.content_type == "application/problem+json"


def test_mfa_enroll_rejects_an_authenticated_customer_with_no_pending_mfa(
    api_client: FlaskClient,
) -> None:
    """A valid customer session must still be rejected: this route is staff-only."""
    assert _register(api_client).status_code == 201
    login_response = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]

    response = api_client.post("/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 401


def test_full_staff_mfa_enrollment_and_verification_flow(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]

    enroll_response = api_client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": csrf_token}
    )
    assert enroll_response.status_code == 200
    enroll_body = enroll_response.get_json()
    secret = enroll_body["secret"]
    assert secret
    assert enroll_body["provisioning_uri"].startswith("otpauth://totp/")

    code = pyotp.TOTP(secret).now()
    verify_response = api_client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": code},
        headers={"X-CSRFToken": csrf_token},
    )

    assert verify_response.status_code == 200
    verify_body = verify_response.get_json()
    assert verify_body["role"] == "adviser"
    assert verify_body["email"] == STAFF_EMAIL
    assert verify_body["csrf_token"]


# --- mfa/enroll: F3 -- a password alone must never (re-)establish MFA -----------------------


def test_mfa_enroll_rejects_re_enrollment_via_a_pending_session_when_already_enrolled(
    api_client: FlaskClient, enrolled_staff_member: Staff
) -> None:
    """A correct password alone must not be enough to replace an existing MFA secret."""
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    assert login_response.status_code == 200
    assert login_response.get_json()["status"] == "mfa_required"
    csrf_token = login_response.get_json()["csrf_token"]

    response = api_client.post("/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 409
    assert response.get_json()["code"] == "mfa_already_enrolled"


def test_mfa_enroll_reset_requires_password_reentry(
    api_client: FlaskClient, enrolled_staff_member: Staff
) -> None:
    """A fully-authenticated staff session must still re-prove the password to replace the
    secret."""
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]
    code = pyotp.TOTP(enrolled_staff_member.totp_secret_encrypted).now()
    verify_response = api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": csrf_token}
    )
    assert verify_response.status_code == 200
    csrf_token = verify_response.get_json()["csrf_token"]

    response = api_client.post(
        "/api/v1/auth/mfa/enroll", json={}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 403


def test_mfa_enroll_reset_rejects_the_wrong_password(
    api_client: FlaskClient, enrolled_staff_member: Staff
) -> None:
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]
    code = pyotp.TOTP(enrolled_staff_member.totp_secret_encrypted).now()
    verify_response = api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": csrf_token}
    )
    csrf_token = verify_response.get_json()["csrf_token"]

    response = api_client.post(
        "/api/v1/auth/mfa/enroll",
        json={"password": "definitely-not-the-password"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 403


def test_mfa_enroll_reset_succeeds_with_the_correct_password(
    api_client: FlaskClient, enrolled_staff_member: Staff
) -> None:
    original_secret = enrolled_staff_member.totp_secret_encrypted
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]
    code = pyotp.TOTP(original_secret).now()
    verify_response = api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": csrf_token}
    )
    csrf_token = verify_response.get_json()["csrf_token"]

    response = api_client.post(
        "/api/v1/auth/mfa/enroll",
        json={"password": STAFF_PASSWORD},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    new_secret = response.get_json()["secret"]
    assert new_secret != original_secret


def test_mfa_verify_rejects_an_invalid_code(api_client: FlaskClient, staff_member: Staff) -> None:
    login_response = _login(api_client, email=STAFF_EMAIL, password=STAFF_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]
    api_client.post("/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": csrf_token})

    response = api_client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": "000000"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 401


def test_mfa_verify_with_no_session_at_all_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.post("/api/v1/auth/mfa/verify", json={"code": "123456"})
    assert response.status_code == 400  # CSRFProtect rejects first — see the mfa/enroll variant.


def test_mfa_verify_rejects_a_session_with_no_pending_mfa(api_client: FlaskClient) -> None:
    assert _register(api_client).status_code == 201
    login_response = _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    csrf_token = login_response.get_json()["csrf_token"]

    response = api_client.post(
        "/api/v1/auth/mfa/verify",
        json={"code": "123456"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 401


# --- throttling --------------------------------------------------------------------------------


def test_login_is_throttled(api_client: FlaskClient) -> None:
    last_response = None
    for _ in range(11):
        last_response = _login(api_client, email="throttle-probe@trueup.example", password="x")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


def test_register_is_throttled(api_client: FlaskClient) -> None:
    last_response = None
    for i in range(6):
        last_response = _register(api_client, email=f"throttle-{i}@trueup.example")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
