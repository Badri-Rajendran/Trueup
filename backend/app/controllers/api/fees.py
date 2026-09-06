"""Fee routes (S10 §7): `GET /api/v1/fees`, `POST /api/v1/payment-methods`. Requires an
authenticated principal owning (or staff authorized for) the named `customer_id`.
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.errors import ForbiddenError, UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import DbRole, limiter
from app.integrations.stripe.billing_adapter import StripeBillingAdapter
from app.services.fees.fee_summary_service import FeeSummary, FeeSummaryService
from app.services.fees.payment_method_service import CustomerNotFoundError, PaymentMethodService
from app.services.fees.uow import FeesUnitOfWork
from app.views.fees import (
    DunningStateResponse,
    FeeChargeResponse,
    FeeSummaryResponse,
    HighWaterMarkResponse,
    PaymentMethodResponse,
)

fees_bp = Blueprint("fees", __name__, url_prefix="/api/v1")


class AttachPaymentMethodRequest(BaseModel):
    customer_id: uuid.UUID
    payment_method_id: str


def _authorize_customer_id(target_customer_id: uuid.UUID) -> None:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role == "customer":
        raw_user_id = flask_session.get("_user_id")
        if not raw_user_id or uuid.UUID(raw_user_id) != target_customer_id:
            raise ForbiddenError("Cannot access resources belonging to another customer")
    elif current_user.role not in ("adviser", "admin"):
        raise ForbiddenError(f"Unknown role {current_user.role}")


def _resolve_customer_id_for_get(raw_query_customer_id: str | None) -> uuid.UUID:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role == "customer":
        raw_user_id = flask_session.get("_user_id")
        if not raw_user_id:
            raise UnauthenticatedError("No authenticated session")
        return uuid.UUID(raw_user_id)
    if not raw_query_customer_id:
        raise ValidationError("customer_id is required for a staff session")
    try:
        return uuid.UUID(raw_query_customer_id)
    except ValueError as exc:
        raise ValidationError("customer_id must be a UUID") from exc


def _session_role_and_customer_id(
    target_customer_id: uuid.UUID,
) -> tuple[SessionRole, uuid.UUID | None]:
    if current_user.role == "customer":
        return SessionRole.CUSTOMER, target_customer_id
    if current_user.role == "adviser":
        return SessionRole.ADVISER, None
    return SessionRole.ADMIN, None


def _build_billing_adapter() -> StripeBillingAdapter:
    settings = get_settings()
    if settings.stripe_secret_key is None:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return StripeBillingAdapter(api_key=settings.stripe_secret_key.get_secret_value())


def _summary_to_view(summary: FeeSummary) -> FeeSummaryResponse:
    hwm = summary.high_water_mark
    dunning = summary.dunning
    return FeeSummaryResponse(
        accrual_to_date=summary.accrual_to_date,
        high_water_mark=(
            HighWaterMarkResponse(peak_value=hwm.peak_value, updated_at=hwm.updated_at)
            if hwm is not None
            else None
        ),
        charges=[
            FeeChargeResponse(
                id=str(charge.id),
                billing_period_start=charge.billing_period_start,
                billing_period_end=charge.billing_period_end,
                total_accrued=charge.total_accrued,
                status=charge.status.value,
                stripe_charge_id=charge.stripe_charge_id,
            )
            for charge in summary.charges
        ],
        dunning=(
            DunningStateResponse(
                fee_charge_id=str(dunning.fee_charge_id),
                attempt_number=dunning.attempt_number,
                next_retry_at=dunning.next_retry_at,
                max_attempts=dunning.max_attempts,
                status=dunning.status.value,
            )
            if dunning is not None
            else None
        ),
    )


@fees_bp.route("/fees", methods=["GET"])
@limiter.limit("30 per minute")
def get_fees() -> Any:
    customer_id = _resolve_customer_id_for_get(request.args.get("customer_id"))
    role, uow_customer_id = _session_role_and_customer_id(customer_id)

    with FeesUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        summary = FeeSummaryService(uow).summarize(customer_id)
        view = _summary_to_view(summary)

    return jsonify(view.model_dump(mode="json")), 200


@fees_bp.route("/payment-methods", methods=["POST"])
@limiter.limit("10 per minute")
def attach_payment_method() -> Any:
    try:
        data = AttachPaymentMethodRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    role, uow_customer_id = _session_role_and_customer_id(data.customer_id)

    with FeesUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        service = PaymentMethodService(uow, payment_port=_build_billing_adapter())
        try:
            method = service.attach(data.customer_id, payment_method_id=data.payment_method_id)
        except CustomerNotFoundError as exc:
            raise ValidationError(str(exc)) from exc
        uow.commit()
        view = PaymentMethodResponse(
            stripe_payment_method_id=method.stripe_payment_method_id,
            updated_at=method.updated_at,
        )

    return jsonify(view.model_dump(mode="json")), 201


__all__ = ["fees_bp"]
