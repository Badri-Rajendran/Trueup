"""Profile routes (ADR 27): read/update the customer's own display name, phone, and mailing
address. Self-scoped only -- the customer is resolved from `flask.session["_user_id"]`
(`chat.py`'s `_current_customer_id` is the precedent this follows), never from a caller-supplied
`customer_id`; there is no such parameter on either route to check (unlike `funding.py`'s
`_resolve_customer_id_for_get`, which trusts a caller-supplied id for staff sessions -- that
pattern does not apply here since no staff/admin read path exists for this data, ADR 27).
"""

from __future__ import annotations

import re
import uuid
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel, field_validator
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ForbiddenError, UnauthenticatedError, ValidationError
from app.core.security import audited
from app.core.uow import SessionRole
from app.extensions import limiter
from app.services.identity.profile_service import ProfileService, ProfileUpdate
from app.services.identity.uow import IdentityUnitOfWork
from app.views.profile import ProfileResponse

if TYPE_CHECKING:
    from app.models.identity.customer import Customer

profile_bp = Blueprint("profile", __name__, url_prefix="/api/v1/profile")

_PHONE_PATTERN = re.compile(r"^\+[1-9]\d{7,14}$")
"""E.164 (ADR 27): a leading '+', a non-zero first digit, 8-15 digits total."""

_MAX_DISPLAY_NAME_LENGTH = 200
_MAX_MAILING_ADDRESS_LENGTH = 500


def _validate_text_field(value: str | None, *, max_length: int) -> str | None:
    """Shared `display_name`/`mailing_address` rule (ADR 27): `None` passes through unchanged (no
    change requested, or an explicit clear); a supplied string must be 1..max_length characters
    after stripping, so an empty or whitespace-only value is rejected rather than silently
    stored. Stores the stripped form -- leading/trailing whitespace is never persisted."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        raise ValueError("must not be empty or whitespace-only")
    if len(stripped) > max_length:
        raise ValueError(f"must be at most {max_length} characters")
    return stripped


class ProfileUpdateRequest(BaseModel):
    """`PATCH /api/v1/profile` body. Partial update (ADR 27): a field omitted here is left
    unchanged; a field present with `null` clears it. The route reads `model_fields_set` to tell
    "omitted" apart from "present and null" -- both are, of necessity, `None` on this model."""

    display_name: str | None = None
    phone: str | None = None
    mailing_address: str | None = None

    @field_validator("display_name")
    @classmethod
    def _check_display_name(cls, value: str | None) -> str | None:
        return _validate_text_field(value, max_length=_MAX_DISPLAY_NAME_LENGTH)

    @field_validator("mailing_address")
    @classmethod
    def _check_mailing_address(cls, value: str | None) -> str | None:
        return _validate_text_field(value, max_length=_MAX_MAILING_ADDRESS_LENGTH)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not _PHONE_PATTERN.match(stripped):
            raise ValueError("must be E.164 format, e.g. +14155552671")
        return stripped


def _current_customer_id() -> uuid.UUID:
    """No `customer_id` parameter exists on either route -- the session is the only source of
    truth (ADR 27)."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Profile is available to customer accounts only")
    raw_user_id = flask_session.get("_user_id")
    if not raw_user_id:
        raise UnauthenticatedError("No authenticated session")
    return uuid.UUID(raw_user_id)


def _field_only_message(exc: PydanticValidationError) -> str:
    """Field names only, never the submitted value (ADR 27, output-encoding discipline) --
    pydantic's own `str(exc)` embeds a repr of the invalid input, which this avoids entirely.
    Populates `ValidationError.detail`, which is server-side only and never rendered to the
    client (`AppError.to_problem()` does not read it) -- but the same discipline applies
    regardless of where the message ends up."""
    fields = sorted({".".join(str(part) for part in err["loc"]) for err in exc.errors()})
    return f"Invalid value for field(s): {', '.join(fields)}"


@profile_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
def get_profile() -> Any:
    customer_id = _current_customer_id()

    with IdentityUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        customer = ProfileService(uow).get(customer_id)
        view = ProfileResponse(
            display_name=customer.display_name,
            phone=customer.phone,
            mailing_address=customer.mailing_address,
        )

    return jsonify(view.model_dump(mode="json")), 200


@profile_bp.route("", methods=["PATCH"])
@limiter.limit("10 per minute")  # PII write: no looser than funding.py's money-movement writes.
def update_profile() -> Any:
    customer_id = _current_customer_id()
    try:
        data = ProfileUpdateRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(_field_only_message(exc)) from exc

    update = ProfileUpdate(fields={name: getattr(data, name) for name in data.model_fields_set})

    with IdentityUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        customer = ProfileService(uow).get(customer_id)
        _apply_update(uow=uow, customer_id=customer_id, customer=customer, update=update)
        uow.commit()
        # Read the already-loaded object, not a second query: RLS's `app.customer_id` SET LOCAL
        # does not outlive the transaction `commit()` just closed (kyc_overrides.py's same trap).
        view = ProfileResponse(
            display_name=customer.display_name,
            phone=customer.phone,
            mailing_address=customer.mailing_address,
        )

    return jsonify(view.model_dump(mode="json")), 200


@audited("identity.profile.update")
def _apply_update(
    *,
    uow: IdentityUnitOfWork,
    customer_id: uuid.UUID,
    customer: Customer,
    update: ProfileUpdate,
) -> None:
    """Indirection so `@audited` sees `uow`/`customer_id` as its own arguments (matches
    `kyc_overrides.py`'s `_apply_override`). `AdminAuditLog.payload_hash` stores a hash of the raw
    request body, never the body itself (ADR 27) -- this never writes PII into the audit trail."""
    ProfileService(uow).apply_update(customer, update)


__all__ = ["profile_bp"]
