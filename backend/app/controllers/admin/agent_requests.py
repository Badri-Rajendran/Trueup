"""Human approval queue for MCP write-tool proposals (S13 §5). Adviser/admin-only.

`approve` executes the row's mapped service call inside a `SAVEPOINT`: an expected domain failure
marks the row `execution_failed` without losing the `approved` transition; an unexpected one
propagates as a normal 500 (ADR 24 point 3).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from flask import Blueprint, jsonify, request
from flask_login import current_user
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.clock import MarketClock
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.pagination import decode_cursor, normalize_limit, paginate
from app.core.security import audited, requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.identity.customer import KycStatus
from app.models.marketdata.trading_calendar import (
    CachedTradingCalendar,
    MarketCalendarCacheMissError,
)
from app.models.ops.agent_action_request import (
    AgentActionRequest,
    AgentActionStatus,
    AgentActionType,
    InvalidAgentActionTransitionError,
)
from app.models.reconciliation.reconciliation_break import AlreadyResolvedError
from app.services.agent_surface.uow import AgentSurfaceUnitOfWork
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_service import CustomerNotEligibleError, OrderService
from app.services.rebalance.drift_evaluation_service import (
    DriftEvaluationService,
    NoAssignedModelError,
)
from app.services.rebalance.rebalance_order_service import RebalanceOrderService, real_order_placer
from app.views.agent_requests import AgentActionRequestResponse, AgentActionRequestsListResponse

agent_requests_bp = Blueprint(
    "admin_agent_requests", __name__, url_prefix="/api/v1/admin/agent-requests"
)

_STAFF_ROLES = ("adviser", "admin")

_EXPECTED_EXECUTION_ERRORS: tuple[type[Exception], ...] = (
    AlreadyResolvedError,
    NoAssignedModelError,
    CustomerNotEligibleError,
    # Operational timing condition, not a bug -- treated as expected, like the three above.
    MarketCalendarCacheMissError,
)


class _ExecutionFailedError(RuntimeError):
    """A precondition an `_execute_*` mapping checks itself; caught the same way as
    `_EXPECTED_EXECUTION_ERRORS` (S13 §6 edge case 1)."""


class _ReviewRequest(BaseModel):
    review_note: str | None = None


class _RejectRequest(BaseModel):
    review_note: str = Field(min_length=1)


def _to_response(row: AgentActionRequest) -> AgentActionRequestResponse:
    return AgentActionRequestResponse(
        id=row.id,
        action=row.action.value,
        arguments=row.arguments,
        requesting_agent=row.requesting_agent,
        justification=row.justification,
        status=row.status.value,
        reviewed_by=row.reviewed_by,
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        execution_error=row.execution_error,
        executed_at=row.executed_at,
        created_at=row.created_at,
    )


def _target_customer_id(row: AgentActionRequest) -> uuid.UUID | None:
    raw = row.arguments.get("customer_id")
    return uuid.UUID(raw) if raw is not None else None


def _decode_request_cursor(raw: str) -> tuple[datetime, uuid.UUID]:
    decoded = decode_cursor(raw)
    if len(decoded) != 2 or not isinstance(decoded[0], str) or not isinstance(decoded[1], str):
        raise ValidationError("invalid pagination cursor")
    try:
        return datetime.fromisoformat(decoded[0]), uuid.UUID(decoded[1])
    except ValueError as exc:
        raise ValidationError("invalid pagination cursor") from exc


@agent_requests_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def list_requests() -> Any:
    raw_status = request.args.get("status", AgentActionStatus.PENDING.value)
    try:
        status = AgentActionStatus(raw_status)
    except ValueError as exc:
        raise ValidationError(f"unknown status {raw_status!r}") from exc

    raw_limit = request.args.get("limit")
    limit = normalize_limit(int(raw_limit)) if raw_limit is not None else normalize_limit(None)
    after: tuple[datetime, uuid.UUID] | None = None
    raw_cursor = request.args.get("cursor")
    if raw_cursor:
        after = _decode_request_cursor(raw_cursor)

    with AgentSurfaceUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        rows = uow.agent_action_requests.list_by_status(status, limit=limit, after=after)
        page = paginate(
            rows, limit=limit, cursor_key=lambda r: (r.created_at.isoformat(), str(r.id))
        )

        view = AgentActionRequestsListResponse(
            requests=[_to_response(row) for row in page.items], next_cursor=page.next_cursor
        )

    return jsonify(view.model_dump(mode="json")), 200


@agent_requests_bp.route("/<uuid:request_id>", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def get_request(request_id: uuid.UUID) -> Any:
    with AgentSurfaceUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        row = uow.agent_action_requests.get_by_id(request_id)
        if row is None:
            raise NotFoundError(f"agent_action_request {request_id} not found")
        view = _to_response(row)

    return jsonify(view.model_dump(mode="json")), 200


@agent_requests_bp.route("/<uuid:request_id>/approve", methods=["POST"])
@limiter.limit("30 per minute")
@requires_role(*_STAFF_ROLES)
def approve(request_id: uuid.UUID) -> Any:
    try:
        body = _ReviewRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    now = datetime.now(UTC)
    with AgentSurfaceUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        row = uow.agent_action_requests.get_for_update(request_id)
        if row is None:
            raise NotFoundError(f"agent_action_request {request_id} not found")

        _approve_request(
            uow=uow,
            target_customer_id=_target_customer_id(row),
            row=row,
            reviewed_by=current_user.id,
            reviewed_at=now,
            review_note=body.review_note,
        )
        uow.commit()
        view = _to_response(row)

    return jsonify(view.model_dump(mode="json")), 200


@agent_requests_bp.route("/<uuid:request_id>/reject", methods=["POST"])
@limiter.limit("30 per minute")
@requires_role(*_STAFF_ROLES)
def reject(request_id: uuid.UUID) -> Any:
    try:
        body = _RejectRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    now = datetime.now(UTC)
    with AgentSurfaceUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        row = uow.agent_action_requests.get_for_update(request_id)
        if row is None:
            raise NotFoundError(f"agent_action_request {request_id} not found")

        _reject_request(
            uow=uow,
            target_customer_id=_target_customer_id(row),
            row=row,
            reviewed_by=current_user.id,
            reviewed_at=now,
            review_note=body.review_note,
        )
        uow.commit()
        view = _to_response(row)

    return jsonify(view.model_dump(mode="json")), 200


@audited("agent_action_request.approve", target_customer_id_param="target_customer_id")
def _approve_request(
    *,
    uow: AgentSurfaceUnitOfWork,
    target_customer_id: uuid.UUID | None,
    row: AgentActionRequest,
    reviewed_by: uuid.UUID,
    reviewed_at: datetime,
    review_note: str | None,
) -> None:
    """Indirection so `@audited` sees `uow`/`target_customer_id` as its own arguments."""
    try:
        uow.agent_action_requests.approve(
            row, reviewed_by=reviewed_by, reviewed_at=reviewed_at, review_note=review_note
        )
    except InvalidAgentActionTransitionError as exc:
        raise ConflictError(str(exc), code="agent_action_request_not_pending") from exc

    try:
        with uow.session.begin_nested():
            _EXECUTORS[row.action](uow, row, reviewed_by, reviewed_at)
    except _EXPECTED_EXECUTION_ERRORS as exc:
        uow.agent_action_requests.mark_execution_failed(row, execution_error=str(exc))
    else:
        uow.agent_action_requests.mark_executed(row, executed_at=reviewed_at)


@audited("agent_action_request.reject", target_customer_id_param="target_customer_id")
def _reject_request(
    *,
    uow: AgentSurfaceUnitOfWork,
    target_customer_id: uuid.UUID | None,
    row: AgentActionRequest,
    reviewed_by: uuid.UUID,
    reviewed_at: datetime,
    review_note: str,
) -> None:
    """Indirection so `@audited` sees `uow`/`target_customer_id` as its own arguments."""
    try:
        uow.agent_action_requests.reject(
            row, reviewed_by=reviewed_by, reviewed_at=reviewed_at, review_note=review_note
        )
    except InvalidAgentActionTransitionError as exc:
        raise ConflictError(str(exc), code="agent_action_request_not_pending") from exc


def _execute_resolve_break(
    uow: AgentSurfaceUnitOfWork,
    row: AgentActionRequest,
    reviewed_by: uuid.UUID,
    reviewed_at: datetime,
) -> None:
    """S13 §5.1: the same service `POST /admin/breaks/<id>/resolve` already calls."""
    break_id = uuid.UUID(row.arguments["break_id"])
    break_row = uow.reconciliation_breaks.get_by_id(break_id)
    if break_row is None:
        raise _ExecutionFailedError(f"reconciliation_break {break_id} not found")
    uow.reconciliation_breaks.resolve(
        break_row,
        resolved_by=reviewed_by,
        resolved_at=reviewed_at,
        resolution_note=row.arguments["resolution_note"],
    )


def _execute_kyc_override(
    uow: AgentSurfaceUnitOfWork,
    row: AgentActionRequest,
    reviewed_by: uuid.UUID,
    reviewed_at: datetime,
) -> None:
    """S13 §5.1: the same service `POST /admin/kyc-overrides/<customer_id>` calls."""
    customer_id = uuid.UUID(row.arguments["customer_id"])
    customer = uow.customers.get_by_id(customer_id)
    if customer is None:
        raise _ExecutionFailedError(f"customer {customer_id} not found")
    customer.kyc_status = KycStatus.pending


def _execute_rebalance(
    uow: AgentSurfaceUnitOfWork,
    row: AgentActionRequest,
    reviewed_by: uuid.UUID,
    reviewed_at: datetime,
) -> None:
    """S13 §5.1: `DriftEvaluationService.evaluate` + the same order-placement path
    `MonthlyRebalanceJob` uses, for this one customer only."""
    customer_id = uuid.UUID(row.arguments["customer_id"])
    if uow.customers.get_by_id(customer_id) is None:
        raise _ExecutionFailedError(f"customer {customer_id} not found")

    settings = get_settings()
    clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
    as_of_date = clock.market_date(datetime.now(UTC))

    drift_evaluator = DriftEvaluationService(uow, drift_band_pct=settings.drift_band_pct)
    cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
    order_service = OrderService(
        uow,
        hold_service=ApprovalHoldService(uow),
        cash_policy=cash_policy,
        approval_threshold_usd=settings.order_approval_threshold_usd,
    )
    rebalance_orders = RebalanceOrderService(
        order_placer=real_order_placer(order_service),
        cash_provider=cash_policy,
        cash_buffer_pct=settings.rebalance_cash_buffer_pct,
    )

    evaluation = drift_evaluator.evaluate(customer_id, as_of_date)
    rebalance_orders.generate_orders(evaluation)


_Executor = Callable[["AgentSurfaceUnitOfWork", "AgentActionRequest", uuid.UUID, datetime], None]

_EXECUTORS: dict[AgentActionType, _Executor] = {
    AgentActionType.RESOLVE_BREAK: _execute_resolve_break,
    AgentActionType.KYC_OVERRIDE: _execute_kyc_override,
    AgentActionType.REBALANCE: _execute_rebalance,
}


__all__ = ["agent_requests_bp"]
