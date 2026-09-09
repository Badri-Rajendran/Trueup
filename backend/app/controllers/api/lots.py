"""Tax lot routes (S8 §3, data owned by S5) -- `GET /api/v1/lots`: quantity, cost basis (original
and wash-sale-adjusted), realized gains, provisional flags, current market value/unrealized gain,
wash-sale-disallowed loss disclosure, and per-sale consumption detail for every lot.

Reads `adjusted_basis`/`realized_gain_loss` (already wash-sale-adjusted, S5 §5); never
`original_cost_basis` except as the immutable "as purchased" reference (S5 §7 edge case 1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user

from app.core.clock import MarketClock
from app.core.errors import UnauthenticatedError, ValidationError
from app.core.pagination import decode_cursor, normalize_limit, paginate
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.services.lots.lots_summary_service import LotsSummaryService, LotSummary
from app.services.lots.uow import LotsUnitOfWork
from app.views.lots import LotConsumptionResponse, LotResponse, LotsListResponse

lots_bp = Blueprint("lots", __name__, url_prefix="/api/v1")

_STAFF_ROLES = ("adviser", "admin")


def _resolve_customer_id() -> uuid.UUID:
    """A `customer` session sees its own data; staff must name whose (FR-31)."""
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
    """`UnitOfWork` requires `customer_id=None` for an adviser/admin session (RLS admits reads)."""
    return customer_id if _session_role() is SessionRole.CUSTOMER else None


def _parse_optional_limit(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError("limit must be an integer") from exc


def _decode_lot_cursor(raw: str) -> tuple[date, uuid.UUID]:
    decoded = decode_cursor(raw)
    if len(decoded) != 2 or not isinstance(decoded[0], str) or not isinstance(decoded[1], str):
        raise ValidationError("invalid pagination cursor")
    try:
        return date.fromisoformat(decoded[0]), uuid.UUID(decoded[1])
    except ValueError as exc:
        raise ValidationError("invalid pagination cursor") from exc


def _lot_to_response(item: LotSummary) -> LotResponse:
    return LotResponse(
        id=str(item.lot.id),
        security_id=str(item.lot.security_id),
        symbol=item.symbol,
        quantity_opened=item.lot.quantity_opened,
        quantity_remaining=item.lot.quantity_remaining,
        original_cost_basis=item.lot.original_cost_basis,
        adjusted_basis=item.lot.adjusted_basis,
        realized_gain_loss=item.realized_gain_loss,
        is_provisional=item.is_provisional,
        acquired_at=item.lot.acquired_at,
        designation=item.lot.designation.value,
        designation_window_closes_at=item.lot.designation_window_closes_at,
        current_price=item.current_price,
        market_value=item.market_value,
        unrealized_gain_loss=item.unrealized_gain_loss,
        wash_sale_disallowed=item.wash_sale_disallowed,
        consumptions=[
            LotConsumptionResponse(
                id=str(consumption.id),
                sale_date=consumption.sale_date,
                quantity_consumed=consumption.quantity_consumed,
                realized_gain_loss=consumption.realized_gain_loss,
                is_provisional=consumption.is_provisional,
            )
            for consumption in item.consumptions
        ],
    )


@lots_bp.route("/lots", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def list_lots() -> Any:
    customer_id = _resolve_customer_id()
    limit = normalize_limit(_parse_optional_limit(request.args.get("limit")))
    after: tuple[date, uuid.UUID] | None = None
    raw_cursor = request.args.get("cursor")
    if raw_cursor:
        after = _decode_lot_cursor(raw_cursor)

    with LotsUnitOfWork(customer_id=_uow_customer_id(customer_id), role=_session_role()) as uow:
        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        as_of_date = clock.market_date(datetime.now(UTC))
        summary = LotsSummaryService(uow).summarize(
            customer_id, as_of_date=as_of_date, limit=limit, after=after
        )
        page = paginate(
            summary.lots,
            limit=limit,
            cursor_key=lambda item: (item.lot.acquired_at.isoformat(), str(item.lot.id)),
        )
        items = [_lot_to_response(item) for item in page.items]

    view = LotsListResponse(lots=items, next_cursor=page.next_cursor)
    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["lots_bp"]
