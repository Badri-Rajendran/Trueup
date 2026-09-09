"""Security catalogue routes: `GET /api/v1/securities` backs a future watchlist feature (a later,
unrelated frontend task). Not tenant-scoped -- any authenticated session (customer or staff) reads
the same active-security list, so there is no ownership check beyond authentication.
"""

from __future__ import annotations

import uuid
from typing import Any

from flask import Blueprint, jsonify, request
from flask import session as flask_session
from flask_login import current_user

from app.core.errors import UnauthenticatedError, ValidationError
from app.core.pagination import normalize_limit
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.marketdata import MarketDataUnitOfWork
from app.services.marketdata.security_catalog_service import SecurityCatalogService
from app.views.securities import (
    DailyCloseSummaryResponse,
    SecuritiesListResponse,
    SecurityResponse,
)

securities_bp = Blueprint("securities", __name__, url_prefix="/api/v1/securities")


def _session_role() -> SessionRole:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    return SessionRole(current_user.role)


def _uow_customer_id(role: SessionRole) -> uuid.UUID | None:
    """`UnitOfWork` requires a non-null `customer_id` for a customer-role session even though this
    catalogue is not tenant-scoped (`app/core/uow.py`'s constructor invariant) -- resolved from the
    session exactly as `app/controllers/api/lots.py`'s `_uow_customer_id` does; a staff session
    passes `None`."""
    if role is not SessionRole.CUSTOMER:
        return None
    raw_user_id = flask_session.get("_user_id")
    if not raw_user_id:
        raise UnauthenticatedError("No authenticated session")
    return uuid.UUID(raw_user_id)


def _parse_optional_limit(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError("limit must be an integer") from exc


@securities_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
def list_securities() -> Any:
    role = _session_role()
    limit = normalize_limit(_parse_optional_limit(request.args.get("limit")))
    after = request.args.get("after")

    with MarketDataUnitOfWork(customer_id=_uow_customer_id(role), role=role) as uow:
        rows, next_cursor = SecurityCatalogService(uow).list_active(limit=limit, after=after)

        view = SecuritiesListResponse(
            securities=[
                SecurityResponse(
                    security_id=security.id,
                    symbol=security.symbol,
                    name=security.name,
                    asset_class=security.asset_class.value,
                    last_close=(
                        DailyCloseSummaryResponse(
                            price=daily_close.close_price,
                            market_date=daily_close.market_date,
                            source=daily_close.source.value,
                            status=daily_close.status.value,
                        )
                        if daily_close is not None
                        else None
                    ),
                )
                for security, daily_close in rows
            ],
            next_cursor=next_cursor,
        )

    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["securities_bp"]
