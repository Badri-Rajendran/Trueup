"""Stripe webhook endpoints via the Flask test client (S2 §6, S10 §7, ADR 9/10): signature
verification and the F4 dedup-on-event-id fix.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
import stripe
from flask.testing import FlaskClient
from pydantic import SecretStr
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.fees.fee_charge import FeeCharge
from app.models.identity.kyc_session import KycSession
from app.models.ledger.journal_entry import JournalEntry
from app.models.ops.inbound_event import InboundEvent
from app.models.ops.job_outbox import JobOutbox

IDENTITY_SECRET = "whsec_test_identity_secret"
BILLING_SECRET = "whsec_test_billing_secret"


@pytest.fixture(autouse=True)
def _webhook_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    # Adds the two webhook secrets `conftest.py`'s default settings fixture doesn't cover.
    settings = get_settings()
    monkeypatch.setattr(settings, "stripe_webhook_secret_identity", SecretStr(IDENTITY_SECRET))
    monkeypatch.setattr(settings, "stripe_webhook_secret_billing", SecretStr(BILLING_SECRET))


_WEBHOOK_TABLES = [
    # Customer is excluded: conftest.py owns its lifecycle at session scope.
    InboundEvent.__table__,
    JournalEntry.__table__,
    KycSession.__table__,
    FeeCharge.__table__,
    JobOutbox.__table__,
]


@pytest.fixture(autouse=True)
def _webhook_tables(owner_engine: Engine) -> Iterator[None]:
    for table in _WEBHOOK_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_WEBHOOK_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _sign(payload: bytes, *, secret: str) -> str:
    return stripe.WebhookSignature.generate_signature_header(
        payload=payload.decode(), secret=secret
    )


def _identity_event(*, event_id: str, session_id: str, status: str) -> bytes:
    body = {
        "id": event_id,
        "type": f"identity.verification_session.{status}"
        if status in ("verified", "processing", "canceled")
        else "identity.verification_session.requires_input",
        "data": {"object": {"id": session_id, "status": status}},
    }
    return json.dumps(body).encode()


def _billing_event(*, event_id: str, payment_intent_id: str, status: str) -> bytes:
    type_by_status = {
        "succeeded": "payment_intent.succeeded",
        "payment_failed": "payment_intent.payment_failed",
        "canceled": "payment_intent.canceled",
        "processing": "payment_intent.processing",
    }
    body = {
        "id": event_id,
        "type": type_by_status[status],
        "data": {"object": {"id": payment_intent_id, "status": status}},
    }
    return json.dumps(body).encode()


def _inbound_event_count(owner_engine: Engine) -> int:
    with Session(bind=owner_engine) as session:
        return len(session.execute(select(InboundEvent)).scalars().all())


# --- stripe_identity: signature verification -------------------------------------------------


def test_stripe_identity_webhook_rejects_an_invalid_signature(api_client: FlaskClient) -> None:
    body = _identity_event(event_id="evt_1", session_id="vs_1", status="verified")

    response = api_client.post(
        "/webhooks/stripe_identity",
        data=body,
        headers={
            "Stripe-Signature": "t=1,v1=not-a-real-signature",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401


def test_stripe_identity_webhook_accepts_a_validly_signed_event(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    body = _identity_event(event_id="evt_1", session_id="vs_1", status="verified")

    response = api_client.post(
        "/webhooks/stripe_identity",
        data=body,
        headers={
            "Stripe-Signature": _sign(body, secret=IDENTITY_SECRET),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    assert _inbound_event_count(owner_engine) == 1


# --- stripe_identity: F4 -- dedup keys on the event id, not the session id -------------------


def test_stripe_identity_webhook_processes_two_different_events_for_the_same_session(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """F4: two distinct events sharing one session id must both persist."""
    first = _identity_event(event_id="evt_1", session_id="vs_shared", status="requires_input")
    second = _identity_event(event_id="evt_2", session_id="vs_shared", status="verified")

    first_response = api_client.post(
        "/webhooks/stripe_identity",
        data=first,
        headers={
            "Stripe-Signature": _sign(first, secret=IDENTITY_SECRET),
            "Content-Type": "application/json",
        },
    )
    second_response = api_client.post(
        "/webhooks/stripe_identity",
        data=second,
        headers={
            "Stripe-Signature": _sign(second, secret=IDENTITY_SECRET),
            "Content-Type": "application/json",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert _inbound_event_count(owner_engine) == 2  # both persisted, neither a duplicate


def test_stripe_identity_webhook_still_dedupes_a_genuine_redelivery(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """The same event id delivered twice must still collapse to one recorded event."""
    body = _identity_event(event_id="evt_redelivered", session_id="vs_1", status="verified")
    signature = _sign(body, secret=IDENTITY_SECRET)

    first_response = api_client.post(
        "/webhooks/stripe_identity",
        data=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    second_response = api_client.post(
        "/webhooks/stripe_identity",
        data=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert _inbound_event_count(owner_engine) == 1


# --- stripe_billing: signature verification ---------------------------------------------------


def test_stripe_billing_webhook_rejects_an_invalid_signature(api_client: FlaskClient) -> None:
    body = _billing_event(event_id="evt_1", payment_intent_id="pi_1", status="succeeded")

    response = api_client.post(
        "/webhooks/stripe_billing",
        data=body,
        headers={
            "Stripe-Signature": "t=1,v1=not-a-real-signature",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401


# --- stripe_billing: F4 -- dedup keys on the event id, not the PaymentIntent id --------------


def test_stripe_billing_webhook_processes_two_different_events_for_the_same_payment_intent(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """F4: two distinct events sharing one PaymentIntent id must both persist."""
    first = _billing_event(event_id="evt_1", payment_intent_id="pi_shared", status="processing")
    second = _billing_event(event_id="evt_2", payment_intent_id="pi_shared", status="succeeded")

    first_response = api_client.post(
        "/webhooks/stripe_billing",
        data=first,
        headers={
            "Stripe-Signature": _sign(first, secret=BILLING_SECRET),
            "Content-Type": "application/json",
        },
    )
    second_response = api_client.post(
        "/webhooks/stripe_billing",
        data=second,
        headers={
            "Stripe-Signature": _sign(second, secret=BILLING_SECRET),
            "Content-Type": "application/json",
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert _inbound_event_count(owner_engine) == 2  # both persisted, neither a duplicate


def test_stripe_billing_webhook_still_dedupes_a_genuine_redelivery(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    body = _billing_event(event_id="evt_redelivered", payment_intent_id="pi_1", status="succeeded")
    signature = _sign(body, secret=BILLING_SECRET)

    first_response = api_client.post(
        "/webhooks/stripe_billing",
        data=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    second_response = api_client.post(
        "/webhooks/stripe_billing",
        data=body,
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert _inbound_event_count(owner_engine) == 1
