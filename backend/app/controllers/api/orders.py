"""Order routes (S3 §6): create, approve, and read. Broker events reach the system over the
`trade_updates` websocket (ADR 22), not a webhook controller here.

`POST /orders` accepts `reference_price` (order's schema has no price field). `symbol` is resolved
from S5's securities catalogue, not the request body. `current_user.id` is never read directly
(`DetachedInstanceError`, see `valuation.py`).
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

from app.config import get_settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthenticatedError,
    ValidationError,
)
from app.core.idempotency import (
    IdempotencyConflictError,
    IdempotencyRecord,
    request_hash,
    resolve_replay,
)
from app.core.money import (  # noqa: TC001 -- Pydantic resolves field annotations at class-build time
    Price,
    Units,
)
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.orders.order import Order, OrderSide, OrderStatus
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_service import (
    CustomerNotEligibleError,
    InsufficientInvestableCashError,
    InvalidOrderTransitionError,
    OrderCreationRequest,
    OrderNotFoundError,
    OrderService,
)
from app.services.orders.uow import OrdersUnitOfWork
from app.views.orders import (
    OrderDetailResponse,
    OrderEventResponse,
    OrderListResponse,
    OrderResponse,
)

orders_bp = Blueprint("orders", __name__, url_prefix="/api/v1/orders")

_STAFF_ROLES = ("adviser", "admin")


class CreateOrderRequest(BaseModel):
    security_id: uuid.UUID
    side: OrderSide
    quantity: Units
    reference_price: Price


def _resolve_customer_id() -> uuid.UUID:
    """A `customer` session acts on its own data; staff must name whose (FR-31)."""
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
    return customer_id if _session_role() is SessionRole.CUSTOMER else None


def _order_service(uow: OrdersUnitOfWork) -> OrderService:
    return OrderService(
        uow,
        hold_service=ApprovalHoldService(uow),
        cash_policy=CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow)),
        approval_threshold_usd=get_settings().order_approval_threshold_usd,
    )


def _to_order_response(uow: OrdersUnitOfWork, order: Order) -> OrderResponse:
    """`symbol` is resolved from S5's securities catalogue; `order` has no `symbol` column."""
    security = uow.securities.get_by_id(order.security_id)
    symbol = security.symbol if security is not None else ""
    return OrderResponse(
        id=order.id,
        customer_id=order.customer_id,
        security_id=order.security_id,
        symbol=symbol,
        side=order.side.value,
        quantity_requested=order.quantity_requested,
        status=order.status.value,
        filled_quantity=order.filled_quantity,
        average_fill_price=order.average_fill_price,
        client_order_id=order.client_order_id,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@orders_bp.route("", methods=["POST"])
@limiter.limit("30 per minute")
def create_order() -> Any:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Only a customer may place an order")

    idempotency_key = request.headers.get("Idempotency-Key")
    if not idempotency_key:
        raise ValidationError("Idempotency-Key header is required (NFR-14)")

    raw_body = request.get_data()
    try:
        data = CreateOrderRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    customer_id = _resolve_customer_id()

    with OrdersUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        existing = uow.idempotency_keys.find(customer_id=customer_id, key=idempotency_key)
        if existing is not None:
            try:
                status, body = resolve_replay(existing, raw_body)
            except IdempotencyConflictError as exc:
                raise ConflictError(str(exc)) from exc
            return jsonify(body), status

        try:
            service = _order_service(uow)
            order = service.create_order(
                OrderCreationRequest(
                    customer_id=customer_id,
                    security_id=data.security_id,
                    side=data.side,
                    quantity=data.quantity,
                    reference_price=data.reference_price,
                )
            )
            if order.status is OrderStatus.APPROVED:
                service.enqueue_submission(order)
        except CustomerNotEligibleError as exc:
            raise ForbiddenError(str(exc)) from exc
        except InsufficientInvestableCashError as exc:
            raise ValidationError(str(exc), code="insufficient_investable_cash") from exc

        view = _to_order_response(uow, order)
        body = view.model_dump(mode="json")
        uow.idempotency_keys.save(
            IdempotencyRecord(
                customer_id=customer_id,
                key=idempotency_key,
                request_hash=request_hash(raw_body),
                response_status=201,
                response_body=body,
                created_at=datetime.now(UTC),
            )
        )
        uow.commit()

    return jsonify(body), 201


@orders_bp.route("/<uuid:order_id>/approve", methods=["POST"])
@limiter.limit("30 per minute")
def approve_order(order_id: uuid.UUID) -> Any:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Only the owning customer may approve an order")

    customer_id = _resolve_customer_id()

    with OrdersUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        # Tenant-scoped get_for_update is the ownership check: another's order is invisible.
        try:
            service = _order_service(uow)
            order = service.approve(order_id)
        except OrderNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except InvalidOrderTransitionError as exc:
            raise ConflictError(str(exc)) from exc

        service.enqueue_submission(order)
        view = _to_order_response(uow, order)
        body = view.model_dump(mode="json")
        uow.commit()

    return jsonify(body), 200


@orders_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
def list_orders() -> Any:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role not in ("customer", *_STAFF_ROLES):
        raise ForbiddenError(f"role {current_user.role} not authorized for this endpoint")

    customer_id = _resolve_customer_id()
    with OrdersUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        orders = uow.orders.list_for_customer(customer_id)
        view = OrderListResponse(orders=[_to_order_response(uow, o) for o in orders])

    return jsonify(view.model_dump(mode="json")), 200


@orders_bp.route("/<uuid:order_id>", methods=["GET"])
@limiter.limit("60 per minute")
def get_order(order_id: uuid.UUID) -> Any:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role not in ("customer", *_STAFF_ROLES):
        raise ForbiddenError(f"role {current_user.role} not authorized for this endpoint")

    customer_id = _resolve_customer_id()
    with OrdersUnitOfWork(
        customer_id=_uow_customer_id(customer_id), role=_session_role()
    ) as uow:
        order = uow.orders.get_by_id(order_id)
        if order is None or order.customer_id != customer_id:
            raise NotFoundError(f"no order found for id={order_id!r}")
        events = uow.order_events.list_for_order(order_id)
        view = OrderDetailResponse(
            order=_to_order_response(uow, order),
            events=[OrderEventResponse.model_validate(e) for e in events],
        )

    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["orders_bp"]
