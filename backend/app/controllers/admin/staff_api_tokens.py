"""Issue/list/revoke the bearer credential an MCP client presents (S13 §3.2, `app/mcp/auth.py`).
Adviser/admin-only, self-service on one's own `staff_id`; issuing is `@audited`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask_login import current_user
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.security import audited, requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.identity.staff_api_token import (
    StaffApiToken,
    generate_staff_api_token,
    hash_staff_api_token,
)
from app.services.identity.uow import IdentityUnitOfWork
from app.views.staff_api_tokens import (
    StaffApiTokenIssuedResponse,
    StaffApiTokensListResponse,
    StaffApiTokenSummaryResponse,
)

if TYPE_CHECKING:
    import uuid

staff_api_tokens_bp = Blueprint(
    "admin_staff_api_tokens", __name__, url_prefix="/api/v1/admin/staff-api-tokens"
)

_STAFF_ROLES = ("adviser", "admin")


class _IssueRequest(BaseModel):
    label: str = Field(min_length=1)


def _to_summary(token: StaffApiToken) -> StaffApiTokenSummaryResponse:
    return StaffApiTokenSummaryResponse(
        id=token.id, label=token.label, created_at=token.created_at, revoked_at=token.revoked_at
    )


@staff_api_tokens_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def list_tokens() -> Any:
    with IdentityUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        rows = uow.staff_api_tokens.list_for_staff(current_user.id)
        view = StaffApiTokensListResponse(tokens=[_to_summary(row) for row in rows])

    return jsonify(view.model_dump(mode="json")), 200


@staff_api_tokens_bp.route("", methods=["POST"])
@limiter.limit("10 per minute")
@requires_role(*_STAFF_ROLES)
def issue_token() -> Any:
    try:
        body = _IssueRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    with IdentityUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        token, raw_token = _issue_token(uow=uow, staff_id=current_user.id, label=body.label)
        uow.commit()
        view = StaffApiTokenIssuedResponse(
            id=token.id, label=token.label, token=raw_token, created_at=token.created_at
        )

    return jsonify(view.model_dump(mode="json")), 201


@staff_api_tokens_bp.route("/<uuid:token_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@requires_role(*_STAFF_ROLES)
def revoke_token(token_id: uuid.UUID) -> Any:
    now = datetime.now(UTC)
    with IdentityUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        token = uow.staff_api_tokens.get_by_id(token_id)
        if token is None:
            raise NotFoundError(f"staff_api_token {token_id} not found")
        if token.staff_id != current_user.id:
            raise ForbiddenError("cannot revoke another staff member's API token")

        uow.staff_api_tokens.revoke(token, revoked_at=now)
        uow.commit()
        view = _to_summary(token)

    return jsonify(view.model_dump(mode="json")), 200


@audited("identity.staff_api_token.issue")
def _issue_token(
    *, uow: IdentityUnitOfWork, staff_id: uuid.UUID, label: str
) -> tuple[StaffApiToken, str]:
    """Indirection so `@audited` sees `uow` as its own argument; no single-customer target."""
    raw_token = generate_staff_api_token()
    token = StaffApiToken(
        staff_id=staff_id, label=label, token_hash=hash_staff_api_token(raw_token)
    )
    uow.staff_api_tokens.add(token)
    uow.session.flush()
    return token, raw_token


__all__ = ["staff_api_tokens_bp"]
