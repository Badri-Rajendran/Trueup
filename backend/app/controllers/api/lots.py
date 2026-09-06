"""Tax lot routes (S8 §3, data owned by S5) -- `GET /api/v1/lots`: quantity, cost basis (original
and wash-sale-adjusted), realized gains, and provisional flags for every lot.

Reads `adjusted_basis`/`realized_gain_loss` (already wash-sale-adjusted, S5 §5); never
`original_cost_basis` except as the immutable "as purchased" reference (S5 §7 edge case 1).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user

from app.core.errors import UnauthenticatedError, ValidationError
from app.core.money import Money
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.services.lots.uow import LotsUnitOfWork
from app.views.lots import LotResponse, LotsListResponse

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


@lots_bp.route("/lots", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role("customer", *_STAFF_ROLES)
def list_lots() -> Any:
    customer_id = _resolve_customer_id()
    with LotsUnitOfWork(customer_id=_uow_customer_id(customer_id), role=_session_role()) as uow:
        lots = uow.tax_lots.list_for_customer(customer_id)
        consumptions_by_lot: dict[uuid.UUID, list[Any]] = defaultdict(list)
        for consumption in uow.lot_consumptions.list_for_lots([lot.id for lot in lots]):
            consumptions_by_lot[consumption.tax_lot_id].append(consumption)

        items = []
        for lot in lots:
            lot_consumptions = consumptions_by_lot.get(lot.id, [])
            realized_gain_loss = Money("0.00")
            for consumption in lot_consumptions:
                realized_gain_loss += consumption.realized_gain_loss
            security = uow.securities.get_by_id(lot.security_id)

            items.append(
                LotResponse(
                    id=str(lot.id),
                    security_id=str(lot.security_id),
                    symbol=security.symbol if security is not None else "",
                    quantity_opened=lot.quantity_opened,
                    quantity_remaining=lot.quantity_remaining,
                    original_cost_basis=lot.original_cost_basis,
                    adjusted_basis=lot.adjusted_basis,
                    realized_gain_loss=realized_gain_loss,
                    is_provisional=any(c.is_provisional for c in lot_consumptions),
                    acquired_at=lot.acquired_at,
                    designation=lot.designation.value,
                    designation_window_closes_at=lot.designation_window_closes_at,
                )
            )

    view = LotsListResponse(lots=items)
    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["lots_bp"]
