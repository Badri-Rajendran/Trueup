"""Valuation & returns routes (S4 §7): balance, returns, and history (FR-18).

Every route is authenticated and tenant-scoped (root `CLAUDE.md`'s non-negotiable): a `customer`
session can only ever see its own data; `adviser`/`admin` may pass `customer_id` explicitly for
FR-31's cross-customer reconciliation view, gated by `@requires_role` plus RLS's role-aware policy
underneath (ADR 17) — the same defense-in-depth `BaseRepository`'s own docstring describes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.core.clock import MarketClock
from app.core.errors import UnauthenticatedError, ValidationError
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.core.watermark import Watermark
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.services.valuation.history_service import HistoryService
from app.services.valuation.twr_service import TwrService
from app.services.valuation.uow import ValuationUnitOfWork
from app.services.valuation.valuation_service import ValuationService
from app.views.valuation import (
    BalanceResponse,
    HistoryEntryResponse,
    HistoryResponse,
    ReturnsResponse,
)

valuation_bp = Blueprint("valuation", __name__, url_prefix="/api/v1/valuation")

_STAFF_ROLES = ("adviser", "admin")


class _ReturnsQuery(BaseModel):
    period_start: datetime
    period_end: datetime


def _resolve_customer_id() -> uuid.UUID:
    """A `customer` session always sees its own data; staff must name whose (FR-31).

    Reads the id from `flask.session["_user_id"]` (flask-login's own cookie key) rather than
    `current_user.id` -- a foundation bug (escalated to `main`, not this sub-project's file to
    fix): `load_user()` (`app/controllers/api/auth.py`) returns its principal from inside a
    `UnitOfWork` that is never committed, so `UnitOfWork.__exit__` rolls back before closing --
    rollback expires every loaded attribute, and the subsequent close detaches the instance, so
    any later access to a *mapped* attribute (`current_user.id`, `current_user.get_id()`, and
    `Staff.role`, though not `Customer.role`, which is a plain Python property) raises
    `DetachedInstanceError` on literally every authenticated request. This reads the same value
    flask-login itself already stored in the session cookie at login time, sidestepping the
    detached instance without touching `current_user`, `app/core/uow.py`, or `app/core/security.py`.
    """
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


@valuation_bp.route("/balance", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def balance() -> Any:
    customer_id = _resolve_customer_id()
    with ValuationUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        as_of_date = clock.market_date(datetime.now(UTC))
        result = ValuationService(uow).value_book(customer_id, as_of_date)

    view = BalanceResponse(
        total_value=result.total_value,
        as_of_date=result.as_of_date,
        completeness=result.completeness,
    )
    return jsonify(view.model_dump(mode="json")), 200


@valuation_bp.route("/returns", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def returns() -> Any:
    customer_id = _resolve_customer_id()
    try:
        query = _ReturnsQuery.model_validate(request.args.to_dict())
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    with ValuationUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        result = TwrService(uow).compute_twr(
            customer_id, query.period_start.date(), query.period_end.date()
        )
        uow.commit()

    view = ReturnsResponse(
        twr=result.twr,
        period_start=result.period_start,
        period_end=result.period_end,
        is_provisional=result.is_provisional,
    )
    return jsonify(view.model_dump(mode="json")), 200


@valuation_bp.route("/history", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def history() -> Any:
    customer_id = _resolve_customer_id()
    with ValuationUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        entries = HistoryService(uow).history(customer_id, as_of=Watermark.live())

    view = HistoryResponse(
        entries=[
            HistoryEntryResponse(
                entry_type=entry.entry_type.value,
                effective_date=entry.effective_date,
                recorded_at=entry.recorded_at,
                amount_money=entry.amount_money,
                quantity_units=entry.quantity_units,
                memo=entry.memo,
            )
            for entry in entries
        ]
    )
    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["valuation_bp"]
