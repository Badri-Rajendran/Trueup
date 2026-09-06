"""`POST /api/v1/admin/kyc-overrides/<customer_id>` (S8 §4 row 5, S2 §9's own deferred reopening
gate resolved here). Adviser/admin-only, `@audited` (a privileged action against another
customer's regulatory state).

**Structural note, matching `app/controllers/api/breaks.py`'s own `@audited` pattern exactly.**
`@audited` needs a `UnitOfWork` among the *decorated function's own* arguments, but this
controller (like every other one) opens `uow` inside a `with` block in the view body -- so the
route opens `uow`, then calls a small inner function (`_apply_override`) taking `uow`/
`customer_id` as explicit keyword arguments, itself `@audited`-decorated.

**The reset never touches `kyc_session` rows** (S2 §3.2: that table is append-only, one row per
attempt). Resetting `customer.kyc_status` back to `pending` is the whole fix -- S2 §9's own text
("a new kyc_session row resets attempt_number's effective count"): the very next
`KycService.start_verification` call is no longer blocked by the `kyc_status == rejected` half of
its lock check (`app/services/identity/kyc_service.py`), since that check requires *both* halves.
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
    """A small indirection purely so `@audited` can see `uow`/`customer_id` as this function's
    own arguments -- see module docstring. `reason` is captured only in the audit log's payload
    hash (via the request body `@audited` already hashes); it has no other effect."""
    customer.kyc_status = KycStatus.pending


__all__ = ["admin_kyc_overrides_bp"]
