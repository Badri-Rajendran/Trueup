"""`GET|PATCH /api/v1/profile` (ADR 27) via the Flask test client: authn, self-scoping (no
`customer_id` parameter exists to manipulate), validation boundaries, audit-row redaction, and
throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.models.identity.customer import Customer
from app.models.ops.admin_audit_log import AdminAuditLog

CUSTOMER_EMAIL = "profile-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
OTHER_EMAIL = "profile-other@trueup.example"

_TABLES = [AdminAuditLog.__table__]


@pytest.fixture(autouse=True)
def _profile_tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


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


# --- authentication --------------------------------------------------------------------------


def test_get_profile_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/profile")

    assert response.status_code == 401


def test_patch_profile_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.patch("/api/v1/profile", json={"display_name": "Jane Doe"})

    assert response.status_code == 400  # CSRFProtect rejects an unauthenticated PATCH first.


# --- happy path / partial-update semantics ----------------------------------------------------


def test_get_profile_starts_all_null(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.get("/api/v1/profile", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 200
    assert response.get_json() == {
        "display_name": None,
        "phone": None,
        "mailing_address": None,
    }


def test_patch_updates_only_supplied_fields(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    first = api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Jane Doe", "phone": "+14155552671"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert first.status_code == 200
    assert first.get_json() == {
        "display_name": "Jane Doe",
        "phone": "+14155552671",
        "mailing_address": None,
    }

    second = api_client.patch(
        "/api/v1/profile",
        json={"mailing_address": "1 Market St, San Francisco, CA 94105"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert second.status_code == 200
    body = second.get_json()
    # display_name/phone untouched by the second, mailing_address-only request.
    assert body["display_name"] == "Jane Doe"
    assert body["phone"] == "+14155552671"
    assert body["mailing_address"] == "1 Market St, San Francisco, CA 94105"


def test_patch_clears_a_field_with_explicit_null(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Jane Doe"},
        headers={"X-CSRFToken": csrf_token},
    )

    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": None},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["display_name"] is None


def test_patch_strips_surrounding_whitespace(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": "  Jane Doe  "},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["display_name"] == "Jane Doe"


# --- validation boundaries ---------------------------------------------------------------------


@pytest.mark.parametrize("value", ["", "   "])
def test_patch_rejects_empty_or_whitespace_only_display_name(
    api_client: FlaskClient, value: str
) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile", json={"display_name": value}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


@pytest.mark.parametrize("value", ["", "   "])
def test_patch_rejects_empty_or_whitespace_only_mailing_address(
    api_client: FlaskClient, value: str
) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile", json={"mailing_address": value}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_patch_accepts_null_display_name_as_no_op_clear(api_client: FlaskClient) -> None:
    """`null` (unlike `""`/whitespace) is a valid, explicit "clear" -- not a validation error."""
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile", json={"display_name": None}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 200
    assert response.get_json()["display_name"] is None


def test_patch_rejects_overlong_display_name(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": "x" * 201},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_patch_rejects_overlong_mailing_address(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile",
        json={"mailing_address": "x" * 501},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


@pytest.mark.parametrize(
    "value",
    [
        "not-a-phone",
        "14155552671",  # missing leading +
        "+0123456789",  # leading digit after + is 0
        "+1234",  # too short
        "+1" + "2" * 20,  # too long
        "+1 415 555 2671",  # embedded whitespace
    ],
)
def test_patch_rejects_malformed_phone(api_client: FlaskClient, value: str) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile", json={"phone": value}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_patch_accepts_valid_e164_phone(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile", json={"phone": "+14155552671"}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 200
    assert response.get_json()["phone"] == "+14155552671"


# --- self-scoping (no customer_id parameter exists to manipulate) ------------------------------


def test_get_profile_never_sees_another_customers_data(api_client: FlaskClient) -> None:
    _, a_csrf = _register_and_login(api_client, email=CUSTOMER_EMAIL)
    api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Customer A", "phone": "+14155552671"},
        headers={"X-CSRFToken": a_csrf},
    )
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": a_csrf})

    _, b_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    response = api_client.get("/api/v1/profile", headers={"X-CSRFToken": b_csrf})

    assert response.status_code == 200
    assert response.get_json() == {"display_name": None, "phone": None, "mailing_address": None}


def test_patch_by_one_customer_never_affects_another(
    api_client: FlaskClient, db_committing: Session
) -> None:
    a_id, a_csrf = _register_and_login(api_client, email=CUSTOMER_EMAIL)
    api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Customer A"},
        headers={"X-CSRFToken": a_csrf},
    )
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": a_csrf})

    _, b_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    # No customer_id field exists on the request schema; even smuggling one in the body changes
    # nothing -- the route resolves the target from the session alone.
    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Customer B", "customer_id": a_id},
        headers={"X-CSRFToken": b_csrf},
    )
    assert response.status_code == 200

    customer_a = db_committing.execute(
        select(Customer).where(Customer.id == uuid.UUID(a_id))
    ).scalar_one()
    assert customer_a.display_name == "Customer A"


# --- audit row: change recorded, PII never persisted into it -----------------------------------


def test_patch_writes_an_audit_row_without_the_raw_pii(
    api_client: FlaskClient, db_committing: Session
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": "Jane Doe", "phone": "+14155552671"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert response.status_code == 200

    rows = db_committing.execute(select(AdminAuditLog)).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.action == "identity.profile.update"
    assert row.target_customer_id == uuid.UUID(customer_id)
    assert row.payload_hash != ""
    assert len(row.payload_hash) == 64  # sha256 hex digest -- a hash, not the payload itself.

    row_repr = f"{row.action}|{row.payload_hash}|{row.target_customer_id}|{row.actor_id}"
    assert "Jane Doe" not in row_repr
    assert "+14155552671" not in row_repr


# --- redaction: PII in a rejected request never reaches the response body ---------------------


def test_validation_error_never_echoes_the_submitted_pii(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    secret_value = "SuperSecretPiiValue12345"

    response = api_client.patch(
        "/api/v1/profile",
        json={"display_name": secret_value * 20},  # over the 200-char bound
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert secret_value not in response.get_data(as_text=True)


# --- throttling --------------------------------------------------------------------------------


def test_patch_profile_is_throttled(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    last_response = None
    for _ in range(11):
        last_response = api_client.patch(
            "/api/v1/profile",
            json={"display_name": "Jane Doe"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
