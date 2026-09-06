"""Admin reconciliation-break routes (S7 §8): list open breaks (aging-sorted, S7 §7) and resolve
one. Adviser/admin-only (S7 §11). `reconciliation_break.customer_id` is nullable (S7 §5.2);
`@audited`/`admin_audit_log.target_customer_id` are `None`-tolerant to match.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask_login import current_user
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.core.errors import NotFoundError, ValidationError
from app.core.security import audited, requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.services.reconciliation.break_aging_service import BreakAgingService
from app.services.reconciliation.uow import ReconciliationUnitOfWork
from app.views.reconciliation import BreakResponse, BreaksListResponse

if TYPE_CHECKING:
    import uuid

    from app.models.reconciliation.reconciliation_break import ReconciliationBreak

breaks_bp = Blueprint("admin_breaks", __name__, url_prefix="/api/v1/admin/breaks")

_STAFF_ROLES = ("adviser", "admin")


class _ResolveRequest(BaseModel):
    resolution_note: str = Field(min_length=1)


def _to_response(break_row: ReconciliationBreak, *, now: datetime) -> BreakResponse:
    age = BreakAgingService.age(break_row, now=now)
    return BreakResponse(
        id=break_row.id,
        break_type=break_row.break_type.value,
        customer_id=break_row.customer_id,
        expected=break_row.expected,
        actual=break_row.actual,
        opened_at=break_row.opened_at,
        age_seconds=int(age.total_seconds()),
        status=break_row.status.value,
        resolved_at=break_row.resolved_at,
        resolved_by=break_row.resolved_by,
        resolution_note=break_row.resolution_note,
    )


@breaks_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def list_breaks() -> Any:
    status = request.args.get("status", "open")
    if status != "open":
        raise ValidationError("only status=open is supported")

    now = datetime.now(UTC)
    with ReconciliationUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        rows = uow.reconciliation_breaks.list_open()
        view = BreaksListResponse(breaks=[_to_response(row, now=now) for row in rows])

    return jsonify(view.model_dump(mode="json")), 200


@breaks_bp.route("/<uuid:break_id>/resolve", methods=["POST"])
@limiter.limit("30 per minute")
@requires_role(*_STAFF_ROLES)
def resolve(break_id: uuid.UUID) -> Any:
    try:
        body = _ResolveRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    now = datetime.now(UTC)
    with ReconciliationUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        break_row = uow.reconciliation_breaks.get_by_id(break_id)
        if break_row is None:
            raise NotFoundError(f"reconciliation_break {break_id} not found")

        _resolve_break(
            uow=uow,
            customer_id=break_row.customer_id,
            break_row=break_row,
            resolved_by=current_user.id,
            resolved_at=now,
            resolution_note=body.resolution_note,
        )
        uow.commit()
        view = _to_response(break_row, now=now)

    return jsonify(view.model_dump(mode="json")), 200


def _apply_resolution(
    uow: ReconciliationUnitOfWork,
    *,
    break_row: ReconciliationBreak,
    resolved_by: uuid.UUID,
    resolved_at: datetime,
    resolution_note: str,
) -> None:
    uow.reconciliation_breaks.resolve(
        break_row,
        resolved_by=resolved_by,
        resolved_at=resolved_at,
        resolution_note=resolution_note,
    )


@audited("reconciliation.break.resolve")
def _resolve_break(
    *,
    uow: ReconciliationUnitOfWork,
    customer_id: uuid.UUID | None,
    break_row: ReconciliationBreak,
    resolved_by: uuid.UUID,
    resolved_at: datetime,
    resolution_note: str,
) -> None:
    """Indirection so `@audited` sees `uow`/`customer_id` as its own arguments."""
    _apply_resolution(
        uow,
        break_row=break_row,
        resolved_by=resolved_by,
        resolved_at=resolved_at,
        resolution_note=resolution_note,
    )


__all__ = ["breaks_bp"]
