"""`GET /api/v1/fees`, `POST /api/v1/payment-methods` (S10 §7) via the Flask test client: happy
path, authn/ownership, and throttling -- matching `test_funding.py`/`test_identity.py`'s exact
conventions (CSRF header, `_register_and_login`, `_reset_rate_limits`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text

from app.controllers.api import fees as fees_controller
from app.integrations.fake.fake_billing import FakeBillingAdapter
from app.models.fees.dunning_state import DunningState
from app.models.fees.fee_accrual import FeeAccrual
from app.models.fees.fee_charge import FeeCharge
from app.models.fees.high_water_mark import HighWaterMark
from app.models.fees.payment_method import PaymentMethod
from app.models.ledger.account import Account
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.inbound_event import InboundEvent

CUSTOMER_EMAIL = "fees-customer@trueup.example"
OTHER_EMAIL = "fees-other@trueup.example"
PASSWORD = "correct-horse-battery"

FEES_TABLES = [
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    HighWaterMark.__table__,
    FeeAccrual.__table__,
    FeeCharge.__table__,
    DunningState.__table__,
    PaymentMethod.__table__,
]


@pytest.fixture(autouse=True)
def _fees_tables(owner_engine: Engine) -> Iterator[None]:
    for table in FEES_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(FEES_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture
def _fake_billing_port(monkeypatch: pytest.MonkeyPatch) -> FakeBillingAdapter:
    port = FakeBillingAdapter()
    monkeypatch.setattr(fees_controller, "_build_billing_adapter", lambda: port)
    return port


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


# --- GET /api/v1/fees -----------------------------------------------------------------------


def test_get_fees_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/fees")

    assert response.status_code == 401


def test_get_fees_happy_path_with_no_history_yet(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    response = api_client.get("/api/v1/fees")

    assert response.status_code == 200
    body = response.get_json()
    assert body["accrual_to_date"] == "0.0000"
    assert body["high_water_mark"] is None
    assert body["charges"] == []
    assert body["dunning"] is None


def test_get_fees_is_throttled(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    last_response = None
    for _ in range(31):
        last_response = api_client.get("/api/v1/fees")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- POST /api/v1/payment-methods -----------------------------------------------------------


def test_attach_payment_method_requires_authentication(api_client: FlaskClient) -> None:
    """`CSRFProtect` runs before any view-level `@login_required` check on every `POST` route in
    this app (see `app/controllers/api/auth.py`'s own note on this ordering) -- a request with no
    session also has no CSRF token, so it is rejected at 400, never reaching the auth check. This
    matches every other POST endpoint in this codebase: none of them assert 401 for an
    unauthenticated POST, precisely because CSRF tokens are only ever issued at login/mfa-verify/
    session-restore (root CLAUDE.md's wire-format contract), so there is no way to send a
    CSRF-valid, session-less request to isolate the authentication check alone."""
    response = api_client.post(
        "/api/v1/payment-methods",
        json={"customer_id": str(uuid.uuid4()), "payment_method_id": "pm_card_visa"},
    )

    assert response.status_code == 400


def test_attach_payment_method_happy_path(
    api_client: FlaskClient, _fake_billing_port: FakeBillingAdapter
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/payment-methods",
        json={"customer_id": customer_id, "payment_method_id": "pm_card_visa"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["stripe_payment_method_id"] == "pm_card_visa"
    assert _fake_billing_port.attached_methods == ["pm_card_visa"]


def test_attach_payment_method_rejects_a_mismatched_customer_id(
    api_client: FlaskClient, _fake_billing_port: FakeBillingAdapter
) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/payment-methods",
        json={"customer_id": other_id, "payment_method_id": "pm_card_visa"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 403


def test_attach_payment_method_is_throttled(
    api_client: FlaskClient, _fake_billing_port: FakeBillingAdapter
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            "/api/v1/payment-methods",
            json={"customer_id": customer_id, "payment_method_id": "pm_card_visa"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
