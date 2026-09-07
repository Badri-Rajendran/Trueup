"""Portfolio-model routes (S8 §3, owning spec S9 §3): list the four model portfolios and
view/select a customer's assignment (FR-7). `assigned_at` is anchored to `MarketClock`
(America/New_York, ADR 12/NFR-13). `current_user.id`/`.role` are read directly here since the
`DetachedInstanceError` bug was fixed before this file was written.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from flask import Blueprint, jsonify, request
from flask_login import current_user
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.clock import MarketClock
from app.core.errors import ForbiddenError, NotFoundError, UnauthenticatedError, ValidationError
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.core.watermark import Watermark
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.services.rebalance.drift_evaluation_service import NoAssignedModelError
from app.services.rebalance.portfolio_holdings_service import HoldingLine, PortfolioHoldingsService
from app.services.rebalance.uow import RebalanceUnitOfWork
from app.services.valuation.portfolio_performance_service import (
    PerformanceRange,
    PortfolioPerformanceService,
)
from app.services.valuation.uow import ValuationUnitOfWork
from app.views.portfolios import (
    AssignmentResponse,
    CurrentAssignmentResponse,
    HoldingResponse,
    ModelPortfolioListResponse,
    ModelPortfolioResponse,
    PerformancePointResponse,
    PortfolioHoldingsResponse,
    PortfolioPerformanceResponse,
    TargetWeightResponse,
)

portfolios_bp = Blueprint("portfolios", __name__, url_prefix="/api/v1/portfolios")

_STAFF_ROLES = ("adviser", "admin")


class AssignModelRequest(BaseModel):
    customer_id: uuid.UUID
    model_portfolio_id: uuid.UUID


class _PerformanceQuery(BaseModel):
    """`range` defaults to `1m` here -- the controller edge, never the service (ADR 26's
    no-silent-default convention for `PortfolioPerformanceService.performance()`'s own
    `range` argument)."""

    range: PerformanceRange = "1m"


def _resolve_customer_id() -> uuid.UUID:
    """A `customer` session sees its own assignment; staff must name whose."""
    if current_user.role == "customer":
        return cast("uuid.UUID", current_user.id)
    raw = request.args.get("customer_id")
    if not raw:
        raise ValidationError("customer_id is required for a staff session")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValidationError("customer_id must be a UUID") from exc


def _authorize_customer_id(target_customer_id: uuid.UUID) -> None:
    """`@login_required` + `@requires_ownership`'s effect; also covers `customer_id` via query."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role == "customer":
        if current_user.id != target_customer_id:
            raise ForbiddenError("Cannot access resources belonging to another customer")
    elif current_user.role not in _STAFF_ROLES:
        raise ForbiddenError(f"Unknown role {current_user.role}")


def _session_role() -> SessionRole:
    return SessionRole(current_user.role)


def _uow_customer_id(customer_id: uuid.UUID) -> uuid.UUID | None:
    return customer_id if _session_role() is SessionRole.CUSTOMER else None


@portfolios_bp.route("/models", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def list_models() -> Any:
    with RebalanceUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        models = uow.model_portfolios.list_active()
        view = ModelPortfolioListResponse(
            models=[
                ModelPortfolioResponse(
                    id=model.id,
                    name=model.name,
                    target_weights=[
                        TargetWeightResponse(
                            security_id=tw.security_id,
                            symbol=_symbol_for(uow, tw.security_id),
                            weight_pct=tw.weight_pct,
                        )
                        for tw in uow.target_weights.list_for_model(model.id)
                    ],
                )
                for model in models
            ]
        )

    return jsonify(view.model_dump(mode="json")), 200


def _symbol_for(uow: RebalanceUnitOfWork, security_id: uuid.UUID) -> str:
    security = uow.securities.get_by_id(security_id)
    return security.symbol if security is not None else ""


@portfolios_bp.route("/assignment", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def get_assignment() -> Any:
    customer_id = _resolve_customer_id()
    with RebalanceUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        assignment = uow.customer_model_assignments.get_by_customer(customer_id)
        view = CurrentAssignmentResponse(
            assignment=_to_assignment_response(assignment) if assignment is not None else None
        )

    return jsonify(view.model_dump(mode="json")), 200


@portfolios_bp.route("/assignment", methods=["POST"])
@limiter.limit("10 per minute")
def create_assignment() -> Any:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")

    try:
        data = AssignModelRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc
    _authorize_customer_id(data.customer_id)

    with RebalanceUnitOfWork(
        customer_id=_uow_customer_id(data.customer_id), role=_session_role()
    ) as uow:
        model = uow.model_portfolios.get_by_id(data.model_portfolio_id)
        if model is None or not model.is_active:
            raise ValidationError(
                "model_portfolio_id does not name an active model portfolio",
                code="model_portfolio_not_found",
            )

        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        assignment = uow.customer_model_assignments.upsert(
            CustomerModelAssignment(
                customer_id=data.customer_id,
                model_portfolio_id=data.model_portfolio_id,
                assigned_at=clock.market_date(datetime.now(UTC)),
            )
        )
        view = _to_assignment_response(assignment)
        uow.commit()

    return jsonify(view.model_dump(mode="json")), 201


def _to_assignment_response(assignment: CustomerModelAssignment) -> AssignmentResponse:
    return AssignmentResponse(
        customer_id=assignment.customer_id,
        model_portfolio_id=assignment.model_portfolio_id,
        assigned_at=assignment.assigned_at,
    )


@portfolios_bp.route("/holdings", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def holdings() -> Any:
    """Live, per-security holdings against the customer's assigned model (Portfolio page
    redesign) -- distinct from `GET /portfolios/models`' target-weight-only view. No assigned
    model is a distinguishable 404, never a 500 or an empty-looking 200 (`DriftEvaluationService`
    cannot evaluate drift with nothing to evaluate against)."""
    customer_id = _resolve_customer_id()
    with RebalanceUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        as_of_date = clock.market_date(datetime.now(UTC))

        try:
            result = PortfolioHoldingsService(
                uow, drift_band_pct=get_settings().drift_band_pct
            ).holdings(customer_id, as_of_date)
        except NoAssignedModelError as exc:
            raise NotFoundError(str(exc), code="no_model_assigned") from exc

        view = PortfolioHoldingsResponse(
            customer_id=result.customer_id,
            as_of_date=result.as_of_date,
            completeness=result.completeness,
            total_value=result.total_value,
            holdings=[_holding_to_response(uow, line) for line in result.holdings],
        )

    return jsonify(view.model_dump(mode="json")), 200


def _holding_to_response(uow: RebalanceUnitOfWork, line: HoldingLine) -> HoldingResponse:
    return HoldingResponse(
        security_id=line.security_id,
        symbol=_symbol_for(uow, line.security_id) if line.security_id is not None else None,
        units=line.units,
        price=line.price,
        market_value=line.market_value,
        current_weight_pct=line.current_weight_pct,
        target_weight_pct=line.target_weight_pct,
        drift_pct=line.drift_pct,
        is_flagged=line.is_flagged,
    )


@portfolios_bp.route("/performance", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def performance() -> Any:
    """Live, as-of-now performance series (ADR 26) -- `GET /api/v1/statements` remains the
    as-published series. `range` is an allowlisted enum, never a free-form date pair."""
    customer_id = _resolve_customer_id()
    try:
        query = _PerformanceQuery.model_validate(request.args.to_dict())
    except PydanticValidationError as exc:
        raise ValidationError(str(exc), code="invalid_range") from exc

    with ValuationUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        today = clock.market_date(datetime.now(UTC))
        result = PortfolioPerformanceService(uow).performance(
            customer_id, performance_range=query.range, as_of=Watermark.live(), today=today
        )

    view = PortfolioPerformanceResponse(
        customer_id=result.customer_id,
        range=result.range,
        period_start=result.period_start,
        period_end=result.period_end,
        cumulative_twr=result.cumulative_twr,
        is_provisional=result.is_provisional,
        points=[
            PerformancePointResponse(as_of_date=point.as_of_date, value=point.value)
            for point in result.points
        ],
    )
    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["portfolios_bp"]
