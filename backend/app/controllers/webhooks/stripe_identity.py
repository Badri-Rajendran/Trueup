"""`POST /webhooks/stripe_identity` (S2 §4/§6, ADR 9) -- Stripe Identity verification-session
events, through the foundation spec's one shared intake path (`EventIntakeService`). No bespoke
webhook mechanism: this controller only verifies the signature, hands the envelope to intake for
dedup + durable recording, and -- once intake accepts it -- applies the verdict via `KycService`
and, when it lands the customer on `kyc_status = approved`, checks `AccountApprovalService`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from pydantic import BaseModel

from app.config import get_settings
from app.controllers.api.auth import csrf
from app.core.errors import UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import DbRole
from app.integrations.stripe.kyc_adapter import StripeIdentitySignatureVerifier
from app.models.ops.inbound_event import InboundEventSource
from app.services.identity.account_approval_service import AccountApprovalService
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.identity.kyc_service import CustomerNotFoundError, KycService
from app.services.intake.event_intake import EventIntakeService, IncomingEvent, IntakeResult

if TYPE_CHECKING:
    from app.services.intake.event_intake import IntakeUnitOfWork

stripe_identity_bp = Blueprint("webhooks_stripe_identity", __name__, url_prefix="/webhooks")

_VERIFICATION_SESSION_EVENT_TYPES = frozenset(
    {
        "identity.verification_session.verified",
        "identity.verification_session.requires_input",
        "identity.verification_session.processing",
        "identity.verification_session.canceled",
    }
)


class _VerificationSessionObject(BaseModel):
    id: str
    status: str


class _StripeEventData(BaseModel):
    object: _VerificationSessionObject


class StripeIdentityWebhookPayload(BaseModel):
    """S0 §6: every provider payload is parsed through a Pydantic model before any service sees
    it -- provider data is untrusted input (OWASP API10)."""

    id: str
    type: str
    data: _StripeEventData


def _funding_uow() -> FundingUnitOfWork:
    return FundingUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP)


def _intake_uow_factory() -> IntakeUnitOfWork:
    return _funding_uow()


def _intake_service() -> EventIntakeService:
    settings = get_settings()
    if settings.stripe_webhook_secret_identity is None:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET_IDENTITY is not configured")
    verifier = StripeIdentitySignatureVerifier(
        webhook_secret=settings.stripe_webhook_secret_identity.get_secret_value()
    )
    return EventIntakeService(uow_factory=_intake_uow_factory, verifier=verifier)


@stripe_identity_bp.route("/stripe_identity", methods=["POST"])
@csrf.exempt  # type: ignore[untyped-decorator]  # flask_wtf ships no py.typed
def stripe_identity_webhook() -> Any:
    raw_body = request.get_data()
    signature = request.headers.get("Stripe-Signature")

    try:
        parsed = StripeIdentityWebhookPayload.model_validate(json.loads(raw_body or b"{}"))
    except (ValueError, TypeError) as exc:
        raise ValidationError("malformed Stripe Identity webhook body") from exc

    event = IncomingEvent(
        source=InboundEventSource.STRIPE,
        # F4 fix: dedupe on the Stripe *event* id (`evt_...`), never the verification-session id.
        # The session id is stable across a session's entire lifecycle (`requires_input` then
        # later `verified` share one), so keying on it made every event after the first for a
        # given session a permanent, silently-dropped "duplicate" -- the customer was then never
        # approved, and no retry could recover it (non-negotiable #2: "out-of-order delivery
        # tolerated"). The session id still travels in the payload for correlation.
        source_event_id=parsed.id,
        payload=parsed.model_dump(mode="json"),
    )
    result = _intake_service().intake(event, raw_payload=raw_body, signature=signature)

    if result is IntakeResult.INVALID_SIGNATURE:
        raise UnauthenticatedError("invalid webhook signature")
    if result is IntakeResult.ACCEPTED and parsed.type in _VERIFICATION_SESSION_EVENT_TYPES:
        _apply_verdict(
            provider_session_id=parsed.data.object.id, stripe_status=parsed.data.object.status
        )

    return jsonify({"status": "ok"}), 200


def _apply_verdict(*, provider_session_id: str, stripe_status: str) -> None:
    settings = get_settings()
    with _funding_uow() as uow:
        kyc_service = KycService(uow, max_attempts=settings.kyc_max_attempts)
        try:
            customer_id = kyc_service.apply_verification_verdict(
                provider_session_id=provider_session_id, stripe_status=stripe_status
            )
        except CustomerNotFoundError:
            uow.commit()
            return

        if customer_id is not None:
            AccountApprovalService(uow).approve_if_eligible(customer_id)
        uow.commit()
