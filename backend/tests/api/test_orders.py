"""`POST/GET /api/v1/orders*` (S3 §6) via the Flask test client: happy path, validation, authn/
authz/ownership, and NFR-14's idempotency replay.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from werkzeug.test import TestResponse

from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.idempotency_key import IdempotencyKey
from app.models.ops.job_outbox import JobOutbox
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.models.orders.order_event import OrderEvent

CUSTOMER_EMAIL = "order-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
# `OrderService.enqueue_submission`/the controller's `_to_order_response` both resolve `symbol`
# from the real securities catalogue now (S5) -- every test payload's `security_id` must name a
# real row, seeded once here rather than a fresh `uuid.uuid4()` per call.
SECURITY_ID = uuid.uuid4()
SECURITY_SYMBOL = "AAPL"


@pytest.fixture(scope="session", autouse=True)
def _order_tables(owner_engine: Engine) -> Iterator[None]:
    tables = [
        Security.__table__,
        CustomerCashLock.__table__,
        Order.__table__,
        OrderEvent.__table__,
        ApprovalHold.__table__,
        IdempotencyKey.__table__,
        JobOutbox.__table__,
    ]
    for table in tables:
        table.create(bind=owner_engine, checkfirst=True)
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        Security(
            id=SECURITY_ID,
            symbol=SECURITY_SYMBOL,
            name="Apple Inc.",
            asset_class=SecurityAssetClass.EQUITY,
        )
    )
    session.commit()
    session.close()
    yield None
    for table in reversed(tables):
        table.drop(bind=owner_engine, checkfirst=True)


@pytest.fixture(autouse=True)
def _clean_order_tables(owner_engine: Engine, _order_tables: None) -> Iterator[None]:
    yield None
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE approval_hold, order_event, \"order\", customer_cash_lock, "
                "idempotency_key, job_outbox RESTART IDENTITY CASCADE"
            )
        )


def _register_and_approve_customer(
    client: FlaskClient, owner_engine: Engine, *, email: str = CUSTOMER_EMAIL
) -> uuid.UUID:
    """Registers via the real endpoint, then directly grants KYC/account approval and creates
    the cash-lock row -- standing in for `AccountApprovalService`'s job (S2), which this
    sub-project does not own and should not re-invoke end to end just to set up a fixture."""
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": CUSTOMER_PASSWORD}
    )
    assert response.status_code == 201
    customer_id = uuid.UUID(response.get_json()["id"])

    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        customer.kyc_status = KycStatus.approved
        customer.account_approval_status = AccountApprovalStatus.approved
        session.add(CustomerCashLock(customer_id=customer_id))
        session.commit()
    finally:
        session.close()
    return customer_id


def _login(client: FlaskClient, *, email: str = CUSTOMER_EMAIL) -> TestResponse:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": CUSTOMER_PASSWORD}
    )


def _authed_client(
    client: FlaskClient, owner_engine: Engine, *, email: str = CUSTOMER_EMAIL
) -> tuple[FlaskClient, str]:
    _register_and_approve_customer(client, owner_engine, email=email)
    login_response = _login(client, email=email)
    assert login_response.status_code == 200
    return client, login_response.get_json()["csrf_token"]


def _create_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "security_id": str(SECURITY_ID),
        "side": "buy",
        "quantity": "10",
        "reference_price": "100.00",
    }
    payload.update(overrides)
    return payload


# --- create: happy path --------------------------------------------------------------------


def test_create_order_at_or_below_threshold_is_approved_immediately(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "approved"
    assert body["side"] == "buy"
    assert body["client_order_id"].startswith("trueup-")


def test_create_order_above_threshold_requires_approval(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="1000", reference_price="100.00"),  # $100,000 notional
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "awaiting_approval"


# --- create: idempotency (NFR-14) ----------------------------------------------------------


def test_create_order_replays_the_same_response_for_a_repeated_idempotency_key(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    key = str(uuid.uuid4())
    payload = _create_payload()

    first = client.post(
        "/api/v1/orders",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/orders",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]


def test_create_order_rejects_a_reused_key_with_a_different_body(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    key = str(uuid.uuid4())

    first = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="99"),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_create_order_without_an_idempotency_key_is_rejected(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders", json=_create_payload(), headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422


# --- create: validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"side": "not-a-side"},
        {"quantity": "not-a-number"},
        {"security_id": "not-a-uuid"},
    ],
)
def test_create_order_rejects_invalid_input(
    api_client: FlaskClient, owner_engine: Engine, overrides: dict[str, Any]
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(**overrides),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422


# --- create: authn/authz --------------------------------------------------------------------


def test_create_order_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 400  # CSRFProtect rejects first, matching auth.py's precedent


# --- approve ----------------------------------------------------------------------------------


def test_approve_transitions_an_awaiting_approval_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="1000", reference_price="100.00"),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.post(
        f"/api/v1/orders/{order_id}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "approved"


def test_approve_a_nonexistent_order_returns_not_found(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        f"/api/v1/orders/{uuid.uuid4()}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 404


def test_approve_an_already_approved_order_is_a_conflict(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),  # below threshold -- already approved
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.post(
        f"/api/v1/orders/{order_id}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 409


# --- read: list/detail, ownership -----------------------------------------------------------


def test_get_order_returns_its_own_order_with_event_history(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["order"]["id"] == order_id
    assert isinstance(body["events"], list)


def test_get_order_rejects_another_customers_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]
    client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    other_client, _ = _authed_client(
        api_client, owner_engine, email="other-customer@trueup.example"
    )

    response = other_client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 404


def test_list_orders_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/orders")
    assert response.status_code == 403
