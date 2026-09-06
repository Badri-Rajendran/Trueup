"""`POST /webhooks/plaid` (S2 §5.2 step 4/§5.4, FR-6/FR-43) -- Plaid `ITEM`/`TRANSFER` events,
through the foundation spec's one shared intake path (`EventIntakeService`). No bespoke webhook
mechanism: this controller only verifies the signature, hands the envelope to intake for dedup +
durable recording, and -- once intake accepts it -- applies the effect via `BankLinkService`
(`ITEM_LOGIN_REQUIRED`, FR-43) or `DepositService` (a bounced ACH return, FR-6).
"""

from __future__ import annotations

import json
import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from contextlib import suppress
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from pydantic import BaseModel

from app.config import get_settings
from app.controllers.api.auth import csrf
from app.core.errors import UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import DbRole
from app.integrations.plaid.bank_adapter import PlaidSignatureVerifier
from app.models.ops.inbound_event import InboundEventSource
from app.services.identity.bank_link_service import BankLinkNotFoundError, BankLinkService
from app.services.identity.deposit_service import (
    DepositService,
    SettlementObligationNotFoundError,
)
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.intake.event_intake import EventIntakeService, IncomingEvent, IntakeResult

if TYPE_CHECKING:
    from app.services.intake.event_intake import IntakeUnitOfWork

plaid_webhooks_bp = Blueprint("webhooks_plaid", __name__, url_prefix="/webhooks")


class PlaidWebhookPayload(BaseModel):
    """S0 §6: every provider payload is parsed through a Pydantic model before any service sees
    it -- provider data is untrusted input (OWASP API10).

    Dedupe key per S0 §6: "Plaid: the webhook's own event identity plus `item_id`" -- modeled here
    as `webhook_code` + `item_id`, since sandbox Plaid webhooks carry no separate event ID field.
    """

    webhook_type: str
    webhook_code: str
    item_id: str | None = None
    settlement_obligation_id: uuid.UUID | None = None


def _funding_uow() -> FundingUnitOfWork:
    return FundingUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP)


def _intake_uow_factory() -> IntakeUnitOfWork:
    return _funding_uow()


def _intake_service() -> EventIntakeService:
    settings = get_settings()
    if settings.plaid_client_id is None or settings.plaid_secret is None:
        raise RuntimeError("PLAID_CLIENT_ID/PLAID_SECRET are not configured")
    verifier = PlaidSignatureVerifier(
        client_id=settings.plaid_client_id.get_secret_value(),
        secret=settings.plaid_secret.get_secret_value(),
        environment=settings.plaid_env,
    )
    return EventIntakeService(uow_factory=_intake_uow_factory, verifier=verifier)


@plaid_webhooks_bp.route("/plaid", methods=["POST"])
@csrf.exempt  # type: ignore[untyped-decorator]  # flask_wtf ships no py.typed
def plaid_webhook() -> Any:
    raw_body = request.get_data()
    signature = request.headers.get("Plaid-Verification")

    try:
        parsed = PlaidWebhookPayload.model_validate(json.loads(raw_body or b"{}"))
    except (ValueError, TypeError) as exc:
        raise ValidationError("malformed Plaid webhook body") from exc

    dedupe_id = f"{parsed.webhook_code}:{parsed.item_id or parsed.settlement_obligation_id}"
    event = IncomingEvent(
        source=InboundEventSource.PLAID,
        source_event_id=dedupe_id,
        payload=parsed.model_dump(mode="json"),
    )
    result = _intake_service().intake(event, raw_payload=raw_body, signature=signature)

    if result is IntakeResult.INVALID_SIGNATURE:
        raise UnauthenticatedError("invalid webhook signature")
    if result is IntakeResult.ACCEPTED:
        _apply_effect(parsed)

    return jsonify({"status": "ok"}), 200


def _apply_effect(parsed: PlaidWebhookPayload) -> None:
    if parsed.webhook_type == "ITEM" and parsed.webhook_code == "ERROR" and parsed.item_id:
        _apply_item_login_required(parsed.item_id)
    elif parsed.webhook_type == "TRANSFER" and parsed.settlement_obligation_id is not None:
        _apply_ach_return(parsed.settlement_obligation_id)


def _apply_item_login_required(plaid_item_id: str) -> None:
    """FR-43. An unmatched `item_id` is logged and ignored rather than raised -- the webhook has
    already been durably recorded by intake, and Plaid must not see anything but 200."""
    with _funding_uow() as uow:
        with suppress(BankLinkNotFoundError):
            BankLinkService(uow).apply_item_login_required(plaid_item_id)
        uow.commit()


def _apply_ach_return(settlement_obligation_id: uuid.UUID) -> None:
    """FR-6. An unmatched obligation id is logged and ignored for the same reason as above."""
    settings = get_settings()
    with _funding_uow() as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=settings.deposit_cap_per_transaction,
            deposit_cap_per_day=settings.deposit_cap_per_day,
        )
        with suppress(SettlementObligationNotFoundError):
            service.apply_ach_return(settlement_obligation_id)
        uow.commit()
