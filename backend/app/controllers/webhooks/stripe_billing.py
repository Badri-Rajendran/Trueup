"""`POST /webhooks/stripe_billing` (S10 §7, ADR 10) — Stripe Billing `payment_intent.*` events,
through the foundation spec's one shared intake path (`EventIntakeService`), keyed on the
PaymentIntent id (this system's `stripe_charge_id`). Mirrors `stripe_identity.py`'s exact shape:
this controller only verifies the signature and hands the envelope to intake for dedupe + durable
recording; once intake accepts it, the verdict is applied via `FeeChargeService`, idempotently (a
webhook confirming what the outbox handler's own synchronous call already applied is a no-op, per
`PaymentPort`'s own docstring).
"""

from __future__ import annotations

import json
from typing import Any

from flask import Blueprint, jsonify, request
from pydantic import BaseModel

from app.config import get_settings
from app.controllers.api.auth import csrf
from app.core.errors import UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import DbRole
from app.integrations.stripe.billing_adapter import StripeBillingSignatureVerifier
from app.models.ops.inbound_event import InboundEventSource
from app.services.fees.fee_charge_service import FeeChargeNotFoundError, FeeChargeService
from app.services.fees.uow import FeesUnitOfWork
from app.services.intake.event_intake import EventIntakeService, IncomingEvent, IntakeResult

stripe_billing_bp = Blueprint("webhooks_stripe_billing", __name__, url_prefix="/webhooks")

_SUCCESS_STATUSES = frozenset({"succeeded"})
_FAILURE_STATUSES = frozenset({"payment_failed", "canceled"})


class _PaymentIntentObject(BaseModel):
    id: str
    status: str


class _StripeEventData(BaseModel):
    object: _PaymentIntentObject


class StripeBillingWebhookPayload(BaseModel):
    """S0 §6: every provider payload is parsed through a Pydantic model before any service sees
    it -- provider data is untrusted input (OWASP API10)."""

    id: str
    type: str
    data: _StripeEventData


def _fees_uow() -> FeesUnitOfWork:
    return FeesUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP)


def _intake_service() -> EventIntakeService:
    settings = get_settings()
    if settings.stripe_webhook_secret_billing is None:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET_BILLING is not configured")
    verifier = StripeBillingSignatureVerifier(
        webhook_secret=settings.stripe_webhook_secret_billing.get_secret_value()
    )
    return EventIntakeService(uow_factory=_fees_uow, verifier=verifier)


@stripe_billing_bp.route("/stripe_billing", methods=["POST"])
@csrf.exempt  # type: ignore[untyped-decorator]  # flask_wtf ships no py.typed marker
def stripe_billing_webhook() -> Any:
    raw_body = request.get_data()
    signature = request.headers.get("Stripe-Signature")

    try:
        parsed = StripeBillingWebhookPayload.model_validate(json.loads(raw_body or b"{}"))
    except (ValueError, TypeError) as exc:
        raise ValidationError("malformed Stripe Billing webhook body") from exc

    event = IncomingEvent(
        source=InboundEventSource.STRIPE,
        source_event_id=parsed.data.object.id,
        payload=parsed.model_dump(mode="json"),
    )
    result = _intake_service().intake(event, raw_payload=raw_body, signature=signature)

    if result is IntakeResult.INVALID_SIGNATURE:
        raise UnauthenticatedError("invalid webhook signature")
    if result is IntakeResult.ACCEPTED:
        _apply_verdict(stripe_charge_id=parsed.data.object.id, status=parsed.data.object.status)

    return jsonify({"status": "ok"}), 200


def _apply_verdict(*, stripe_charge_id: str, status: str) -> None:
    with _fees_uow() as uow:
        charge = uow.fee_charges.get_by_stripe_charge_id(stripe_charge_id)
        if charge is None:
            # Either the outbox handler hasn't set stripe_charge_id yet (a benign race -- the
            # eventual consistency window between the synchronous PaymentIntent response and this
            # webhook), or the event names a charge this system never initiated. Neither is an
            # error to surface to Stripe; acknowledge and move on.
            uow.commit()
            return

        service = FeeChargeService(uow)
        try:
            if status in _SUCCESS_STATUSES:
                service.apply_charge_success(charge.id, stripe_charge_id=stripe_charge_id)
            elif status in _FAILURE_STATUSES:
                service.apply_charge_failure(charge.id)
        except FeeChargeNotFoundError:
            pass
        uow.commit()


__all__ = ["stripe_billing_bp"]
