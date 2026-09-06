"""`POST /api/v1/admin/kyc-overrides/<customer_id>` (S8 §4 row 5, S2 §9). Adviser/admin-only,
`@audited`. Resets `customer.kyc_status` to `pending`; never touches `kyc_session` rows (S2 §3.2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask_login import current_user
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import NotFoundError, ValidationError
from app.core.security import audited, requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.identity.customer import KycStatus
from app.services.identity.uow import IdentityUnitOfWork
from app.views.identity import IdentityStatusResponse

if TYPE_CHECKING:
    import uuid

    from app.models.identity.customer import Customer

admin_kyc_overrides_bp = Blueprint(
    "admin_kyc_overrides", __name__, url_prefix="/api/v1/admin/kyc-overrides"
)

_STAFF_ROLES = ("adviser", "admin")


class _OverrideRequest(BaseModel):
    reason: str = Field(min_length=1)


@admin_kyc_overrides_bp.route("/<uuid:customer_id>", methods=["POST"])
@limiter.limit("10 per minute")
@requires_role(*_STAFF_ROLES)
def override_kyc_lock(customer_id: uuid.UUID) -> Any:
    try:
        body = _OverrideRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    with IdentityUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        customer = uow.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")

        _apply_override(uow=uow, customer_id=customer_id, customer=customer, reason=body.reason)
        uow.commit()

        view = IdentityStatusResponse(
            kyc_status=customer.kyc_status.value,
            account_approval_status=customer.account_approval_status.value,
        )

    return jsonify(view.model_dump(mode="json")), 200


@audited("identity.kyc.override")
def _apply_override(
    *, uow: IdentityUnitOfWork, customer_id: uuid.UUID, customer: Customer, reason: str
) -> None:
    """Indirection so `@audited` sees `uow`/`customer_id` as its own arguments."""
    customer.kyc_status = KycStatus.pending


__all__ = ["admin_kyc_overrides_bp"]
