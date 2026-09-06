"""Admin rebalance visibility route (foundation spec `docs/specs/0-backend-foundation-design.md`
§13's routing table: "S9 | `admin/rebalance.py` (visibility only -- rebalance itself is
system-initiated)"). Read-only: shows one customer's current drift status against their assigned
model, computed live via the same `DriftEvaluationService` `MonthlyRebalanceJob` uses -- never
generates an order itself, matching `app/controllers/api/breaks.py`'s `@requires_role` pattern for
an adviser/admin-only route (a customer session gets 403, never 404, per the foundation spec's
general error-response discipline).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify
from flask_login import current_user

from app.config import get_settings
from app.core.clock import MarketClock
from app.core.errors import NotFoundError
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.services.rebalance.drift_evaluation_service import (
    DriftEvaluationService,
    NoAssignedModelError,
)
from app.services.rebalance.uow import RebalanceUnitOfWork
from app.views.rebalance import DriftHoldingResponse, RebalanceStatusResponse

if TYPE_CHECKING:
    import uuid

admin_rebalance_bp = Blueprint(
    "admin_rebalance", __name__, url_prefix="/api/v1/admin/rebalance"
)

_STAFF_ROLES = ("adviser", "admin")


@admin_rebalance_bp.route("/<uuid:customer_id>", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def get_rebalance_status(customer_id: uuid.UUID) -> Any:
    with RebalanceUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        as_of_date = clock.market_date(datetime.now(UTC))

        try:
            evaluation = DriftEvaluationService(
                uow, drift_band_pct=get_settings().drift_band_pct
            ).evaluate(customer_id, as_of_date)
        except NoAssignedModelError as exc:
            raise NotFoundError(str(exc)) from exc

        view = RebalanceStatusResponse(
            customer_id=customer_id,
            model_portfolio_id=evaluation.model_portfolio_id,
            as_of_date=evaluation.as_of_date,
            completeness=evaluation.completeness,
            total_value=evaluation.total_value,
            holdings=[
                DriftHoldingResponse(
                    security_id=entry.security_id,
                    symbol=_symbol_for(uow, entry.security_id),
                    current_market_value=entry.current_market_value,
                    target_market_value=entry.target_market_value,
                    current_weight_pct=entry.current_weight_pct,
                    target_weight_pct=entry.target_weight_pct,
                    is_flagged=entry.is_flagged,
                    direction=entry.direction,
                )
                for entry in evaluation.entries
            ],
        )

    return jsonify(view.model_dump(mode="json")), 200


def _symbol_for(uow: RebalanceUnitOfWork, security_id: uuid.UUID | None) -> str | None:
    if security_id is None:
        return None
    security = uow.securities.get_by_id(security_id)
    return security.symbol if security is not None else ""


__all__ = ["admin_rebalance_bp"]
