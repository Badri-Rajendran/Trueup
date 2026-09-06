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

from app.core.clock import MarketClock
from app.core.errors import ForbiddenError, UnauthenticatedError, ValidationError
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.services.rebalance.uow import RebalanceUnitOfWork
from app.views.portfolios import (
    AssignmentResponse,
    CurrentAssignmentResponse,
    ModelPortfolioListResponse,
    ModelPortfolioResponse,
    TargetWeightResponse,
)

portfolios_bp = Blueprint("portfolios", __name__, url_prefix="/api/v1/portfolios")

_STAFF_ROLES = ("adviser", "admin")


class AssignModelRequest(BaseModel):
    customer_id: uuid.UUID
    model_portfolio_id: uuid.UUID


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
    """`@login_required` + `@requires_ownership`'s effect; also covers `customer_id` via query string."""
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


__all__ = ["portfolios_bp"]
