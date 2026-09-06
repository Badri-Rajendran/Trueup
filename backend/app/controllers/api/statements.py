"""Statements routes (S6 §8, FR-25/26) — the as-published figures S8/S11 both read identically.

Every route is authenticated and tenant-scoped (root `CLAUDE.md`'s non-negotiable), following
`app/controllers/api/valuation.py`'s exact pattern: a `customer` session only ever sees its own
data; `adviser`/`admin` pass `customer_id` explicitly (FR-31), gated by `@requires_role` plus RLS's
role-aware policy underneath (ADR 17).
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date, datetime
from typing import Any

from flask import Blueprint, Response, jsonify, request
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


_EXPORT_CSV_HEADER = [
    "symbol",
    "quantity_consumed",
    "original_cost_basis",
    "adjusted_basis",
    "realized_gain_loss",
    "is_provisional",
]


@statements_bp.route("/<period_start>/export", methods=["GET"])
@limiter.limit("30 per minute")
@requires_role("customer", *_STAFF_ROLES)
def export_statement(period_start: str) -> Any:
    """`GET /api/v1/statements/<period>/export` (S8 §5, FR-36) -- a CSV of every lot consumption
    realized within the as-published period, never the raw pre-wash-sale-adjustment figure (S5's
    own explicit warning, S8 §3's route table). A period never published returns a clear
    "not yet published" `404` rather than falling back to a live-derived export (S8 §6 case 1)."""
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
            raise NotFoundError(
                "This period has not been published yet; a tax export always reflects the "
                "as-published statement, never a live-derived figure",
                code="statement_not_published",
            )

        consumptions = uow.lot_consumptions.list_realized_in_period(
            customer_id, period_start=snapshot.period_start, period_end=snapshot.period_end
        )
        lots_by_id = {
            lot.id: lot
            for lot in uow.tax_lots.list_by_ids([c.tax_lot_id for c in consumptions])
        }
        symbol_by_security_id: dict[uuid.UUID, str] = {}

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_EXPORT_CSV_HEADER)
        for consumption in consumptions:
            lot = lots_by_id[consumption.tax_lot_id]
            if lot.security_id not in symbol_by_security_id:
                security = uow.securities.get_by_id(lot.security_id)
                symbol_by_security_id[lot.security_id] = (
                    security.symbol if security is not None else ""
                )
            writer.writerow(
                [
                    symbol_by_security_id[lot.security_id],
                    str(consumption.quantity_consumed),
                    str(lot.original_cost_basis),
                    str(lot.adjusted_basis),
                    str(consumption.realized_gain_loss),
                    str(consumption.is_provisional).lower(),
                ]
            )

    response = Response(buffer.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = (
        f'attachment; filename="statement-{parsed_period_start.isoformat()}.csv"'
    )
    return response


__all__ = ["statements_bp"]
