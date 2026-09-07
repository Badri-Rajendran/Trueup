"""Order routes (S3 §6): create, approve, cancel-request, and read. Broker events reach the
system over the `trade_updates` websocket (ADR 22), not a webhook controller here; `cancel_order`
below only *requests* a cancellation (ADR 25) -- it never sets `OrderStatus.CANCELED` itself.

`POST /orders` accepts `reference_price` (order's schema has no price field). `symbol` is resolved
from S5's securities catalogue, not the request body. `current_user.id` is never read directly
(`DetachedInstanceError`, see `valuation.py`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

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
from app.core.money import Price, Units
from app.core.security import audited
from app.core.uow import SessionRole
from app.extensions import limiter
from app.integrations.alpaca.broker_adapter import AlpacaBrokerAdapter
from app.models.orders.order import Order, OrderSide, OrderStatus
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_service import (
    CustomerNotEligibleError,
    InsufficientInvestableCashError,
    InvalidOrderTransitionError,
    OrderCreationRequest,
    OrderNotCancellableError,
    OrderNotFoundError,
    OrderService,
)
from app.services.orders.uow import OrdersUnitOfWork
from app.views.orders import (
    ConsumedLotResponse,
    OpenedLotResponse,
    OrderDetailResponse,
    OrderEventResponse,
    OrderListResponse,
    OrderResponse,
)

if TYPE_CHECKING:
    from app.integrations.ports import BrokerPort

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


def _build_broker_port() -> BrokerPort:
    """The live `BrokerPort`, built here so tests can substitute a fake via monkeypatch (mirrors
    `identity.py`'s `_build_kyc_port`)."""
    settings = get_settings()
    if not settings.has_alpaca_credentials:
        raise RuntimeError("ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY is not configured")
    return AlpacaBrokerAdapter(
        api_key_id=settings.alpaca_api_key_id.get_secret_value(),  # type: ignore[union-attr]
        api_secret_key=settings.alpaca_api_secret_key.get_secret_value(),  # type: ignore[union-attr]
    )


# Customer-safe allowlist for `CustomerNotEligibleError.reason` (S2's KYC/account-approval gate).
# `str(exc)`/the raw internal reason must never reach the wire -- only these disclosable codes,
# never a KYC-provider-specific denial detail (Stripe Identity's own reason strings included).
_DEFAULT_INELIGIBILITY_CODE = "customer_not_eligible"
_CUSTOMER_SAFE_INELIGIBILITY_CODES: dict[str, str] = {
    "customer_not_found": _DEFAULT_INELIGIBILITY_CODE,
    "kyc_status_pending": "kyc_verification_pending",
    "kyc_status_rejected": "kyc_verification_rejected",
    "account_approval_status_pending": "account_approval_pending",
    "account_approval_status_rejected": "account_approval_rejected",
}


def _ineligibility_code(exc: CustomerNotEligibleError) -> str:
    """Never falls through to the raw `exc.reason`: an unmapped reason -- e.g. a future gate this
    allowlist hasn't been extended for yet -- degrades to the generic safe code, not a leak."""
    return _CUSTOMER_SAFE_INELIGIBILITY_CODES.get(exc.reason, _DEFAULT_INELIGIBILITY_CODE)


def _to_event_response(event: OrderEvent) -> OrderEventResponse:
    """Only a `fill` event's payload carries `quantity`/`price` (`trade_update_handler.py`)."""
    quantity: Units | None = None
    price: Price | None = None
    if event.event_type is OrderEventType.FILL:
        raw_quantity = event.payload.get("quantity")
        raw_price = event.payload.get("price")
        quantity = Units(str(raw_quantity)) if raw_quantity is not None else None
        price = Price(str(raw_price)) if raw_price is not None else None
    return OrderEventResponse(
        seq=event.seq,
        event_type=event.event_type.value,
        execution_id=event.execution_id,
        quantity=quantity,
        price=price,
        recorded_at=event.recorded_at,
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
            raise ForbiddenError(
                "Customer is not eligible to place orders", code=_ineligibility_code(exc)
            ) from exc
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


@audited("orders.cancel_requested")
def _audited_request_cancel(
    *,
    uow: OrdersUnitOfWork,
    customer_id: uuid.UUID,
    order_id: uuid.UUID,
    service: OrderService,
    broker: BrokerPort,
) -> Order:
    """Indirection so `@audited` sees `uow`/`customer_id` as its own arguments (mirrors
    `admin/kyc_overrides.py`'s `_apply_override`); both are read by the decorator via call-frame
    introspection, not used in this body."""
    return service.request_cancel(order_id, broker=broker)


@orders_bp.route("/<uuid:order_id>/cancel", methods=["POST"])
@limiter.limit("30 per minute")
def cancel_order(order_id: uuid.UUID) -> Any:
    """ADR 25: requests broker cancellation; never itself sets `canceled` -- see
    `OrderService.request_cancel`. `200` here means "the broker was asked", not "canceled"."""
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Only the owning customer may cancel an order")

    customer_id = _resolve_customer_id()

    with OrdersUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        # Tenant-scoped get_for_update is the ownership check: another's order is invisible.
        try:
            service = _order_service(uow)
            order = _audited_request_cancel(
                uow=uow,
                customer_id=customer_id,
                order_id=order_id,
                service=service,
                broker=_build_broker_port(),
            )
        except OrderNotFoundError as exc:
            raise NotFoundError(str(exc)) from exc
        except OrderNotCancellableError as exc:
            raise ConflictError(str(exc)) from exc

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
        events = uow.order_events.list_for_order(order_id)  # already `seq`-ordered

        # Lot linkage (S5 FK): one bulk query keyed on this order's own fill execution IDs --
        # never N+1. A buy shows the lots it opened; a sell shows the lots it consumed.
        fill_execution_ids = [e.execution_id for e in events if e.execution_id is not None]
        opened_lots: list[OpenedLotResponse] = []
        consumed_lots: list[ConsumedLotResponse] = []
        if order.side is OrderSide.BUY:
            opened_lots = [
                OpenedLotResponse.model_validate(lot)
                for lot in uow.tax_lots.list_by_opening_execution_ids(fill_execution_ids)
            ]
        else:
            consumed_lots = [
                ConsumedLotResponse.model_validate(consumption)
                for consumption in uow.lot_consumptions.list_by_closing_execution_ids(
                    fill_execution_ids
                )
            ]

        view = OrderDetailResponse(
            order=_to_order_response(uow, order),
            events=[_to_event_response(e) for e in events],
            opened_lots=opened_lots,
            consumed_lots=consumed_lots,
        )

    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["orders_bp"]
