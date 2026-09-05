"""Identity routes (S2 §6): start a Stripe Identity verification session, read both approval
gates. Both routes require an authenticated principal owning (or a staff member authorized for)
the named `customer_id`.

**`current_user.id` is never read directly** -- a foundation bug (escalated to `main`, not this
sub-project's file to fix; `app/controllers/api/valuation.py`'s `_resolve_customer_id` documents
it first): `load_user()` (`app/controllers/api/auth.py`) returns its principal from inside a
`UnitOfWork` that is never committed, so `UnitOfWork.__exit__` rolls back before closing --
rollback expires every loaded attribute, and the subsequent close detaches the instance, so any
later access to a *mapped* attribute (`current_user.id`, `Staff.role`, though not `Customer.role`,
a plain Python property) raises `DetachedInstanceError` on literally every authenticated request.
This is also why `@requires_ownership` (`app/core/security.py`) is not used here -- it reads
`current_user.id` directly. `_authorize_customer_id` below reads the same value flask-login itself
already stored in the session cookie at login time instead, matching `valuation.py`'s own
`_resolve_customer_id` workaround, applied to a POST body's `customer_id` instead of a query
parameter.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.errors import ForbiddenError, UnauthenticatedError, ValidationError
from app.core.uow import SessionRole
from app.extensions import DbRole, limiter
from app.integrations.stripe.kyc_adapter import StripeKycAdapter
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.identity.kyc_service import KycService
from app.views.identity import IdentityStatusResponse, KycSessionResponse

if TYPE_CHECKING:
    from app.integrations.ports import KycPort

identity_bp = Blueprint("identity", __name__, url_prefix="/api/v1/identity")


class StartKycSessionRequest(BaseModel):
    customer_id: uuid.UUID


def _build_kyc_port() -> KycPort:
    """The live `KycPort`, built here rather than inline so `tests/api/` can substitute a real
    fake (`FakeKycAdapter`, structurally identical to `StripeKycAdapter`) via monkeypatch, without
    the request handler ever branching on "are we under test" -- this endpoint's whole contract is
    a synchronous provider call (S2 §6: the response must carry Stripe's real `client_secret`), so
    there is no async seam to defer it through, unlike order submission (ADR 7)."""
    settings = get_settings()
    if settings.stripe_secret_key is None:
        raise RuntimeError("STRIPE_SECRET_KEY is not configured")
    return StripeKycAdapter(api_key=settings.stripe_secret_key.get_secret_value())


def _authorize_customer_id(target_customer_id: uuid.UUID) -> None:
    """`@login_required` + `@requires_ownership('customer_id')`'s effect, without the
    `current_user.id` access that decorator makes (see module docstring)."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role == "customer":
        raw_user_id = flask_session.get("_user_id")
        if not raw_user_id or uuid.UUID(raw_user_id) != target_customer_id:
            raise ForbiddenError("Cannot access resources belonging to another customer")
    elif current_user.role not in ("adviser", "admin"):
        raise ForbiddenError(f"Unknown role {current_user.role}")


def _session_role_and_customer_id(
    target_customer_id: uuid.UUID,
) -> tuple[SessionRole, uuid.UUID | None]:
    if current_user.role == "customer":
        return SessionRole.CUSTOMER, target_customer_id
    if current_user.role == "adviser":
        return SessionRole.ADVISER, None
    return SessionRole.ADMIN, None


@identity_bp.route("/kyc-sessions", methods=["POST"])
@limiter.limit("5 per minute")
def start_kyc_session() -> Any:
    try:
        data = StartKycSessionRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    settings = get_settings()
    role, uow_customer_id = _session_role_and_customer_id(data.customer_id)

    with FundingUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        service = KycService(
            uow, kyc_port=_build_kyc_port(), max_attempts=settings.kyc_max_attempts
        )
        handle = service.start_verification(data.customer_id)
        uow.commit()

    view = KycSessionResponse(
        provider_session_id=handle.provider_session_id, client_secret=handle.client_secret
    )
    return jsonify(view.model_dump(mode="json")), 201


@identity_bp.route("/status/<uuid:customer_id>", methods=["GET"])
@limiter.limit("30 per minute")
def get_identity_status(customer_id: uuid.UUID) -> Any:
    _authorize_customer_id(customer_id)
    role, uow_customer_id = _session_role_and_customer_id(customer_id)

    with FundingUnitOfWork(customer_id=uow_customer_id, role=role, db_role=DbRole.APP) as uow:
        customer = uow.customers.get_by_id(customer_id)
        if customer is None:
            raise ValidationError("customer not found")
        view = IdentityStatusResponse(
            kyc_status=customer.kyc_status.value,
            account_approval_status=customer.account_approval_status.value,
        )

    return jsonify(view.model_dump(mode="json")), 200
