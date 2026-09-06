"""Statements routes (S6 §8, FR-25/26) — the as-published figures S8/S11 both read identically.

Every route is authenticated and tenant-scoped (root `CLAUDE.md`'s non-negotiable), following
`app/controllers/api/valuation.py`'s exact pattern: a `customer` session only ever sees its own
data; `adviser`/`admin` pass `customer_id` explicitly (FR-31), gated by `@requires_role` plus RLS's
role-aware policy underneath (ADR 17).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user

from app.core.errors import NotFoundError, UnauthenticatedError, ValidationError
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.services.restatement.uow import RestatementUnitOfWork
from app.views.statements import (
    StatementDetailResponse,
    StatementsListResponse,
    StatementSummaryResponse,
)

statements_bp = Blueprint("statements", __name__, url_prefix="/api/v1/statements")

_STAFF_ROLES = ("adviser", "admin")


def _resolve_customer_id() -> uuid.UUID:
    """A `customer` session always sees its own data; staff must name whose (FR-31). See
    `app/controllers/api/valuation.py::_resolve_customer_id`'s own docstring for why this reads
    `flask.session["_user_id"]` rather than `current_user.id`."""
    if current_user.role == "customer":
        raw_user_id = flask_session.get("_user_id")
        if not raw_user_id:
            raise UnauthenticatedError("No authenticated session")
        return uuid.UUID(raw_user_id)
    raw = request.args.get("customer_id")
    if not raw:
        raise ValidationError("customer_id is required for a staff session")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValidationError("customer_id must be a UUID") from exc


def _session_role() -> SessionRole:
    return SessionRole(current_user.role)


def _uow_customer_id(customer_id: uuid.UUID) -> uuid.UUID | None:
    """`UnitOfWork` requires `customer_id=None` for an adviser/admin session (RLS's role branch,
    not `customer_id`, is what admits their reads — `app/core/uow.py`)."""
    return customer_id if _session_role() is SessionRole.CUSTOMER else None


@statements_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def list_statements() -> Any:
    customer_id = _resolve_customer_id()
    with RestatementUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        snapshots = uow.published_snapshots.list_for_customer(customer_id)

    view = StatementsListResponse(
        statements=[
            StatementSummaryResponse(
                period_start=snapshot.period_start,
                period_end=snapshot.period_end,
                publish_watermark=snapshot.publish_watermark,
                twr=snapshot.twr,
                balance=snapshot.balance,
            )
            for snapshot in snapshots
        ]
    )
    return jsonify(view.model_dump(mode="json")), 200


@statements_bp.route("/<period_start>", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def get_statement(period_start: str) -> Any:
    customer_id = _resolve_customer_id()
    try:
        parsed_period_start = date.fromisoformat(period_start)
    except ValueError as exc:
        raise ValidationError("period must be an ISO date (YYYY-MM-DD)") from exc

    raw_watermark = request.args.get("publish_watermark")
    watermark_dt: datetime | None = None
    if raw_watermark:
        try:
            watermark_dt = datetime.fromisoformat(raw_watermark)
        except ValueError as exc:
            raise ValidationError("publish_watermark must be an ISO 8601 datetime") from exc

    with RestatementUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        snapshot = (
            uow.published_snapshots.at_watermark_for_period(
                customer_id, parsed_period_start, watermark_dt
            )
            if watermark_dt is not None
            else uow.published_snapshots.latest_for_period(customer_id, parsed_period_start)
        )

    if snapshot is None:
        raise NotFoundError("No published statement for this period")

    view = StatementDetailResponse(
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        publish_watermark=snapshot.publish_watermark,
        published_at=snapshot.published_at,
        twr=snapshot.twr,
        balance=snapshot.balance,
        holdings=snapshot.holdings_json,
    )
    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["statements_bp"]
