"""Admin customer directory/detail/fees routes (S8 §4 rows 1, 2, 6). Adviser/admin-only.

Reuses `ValuationService.value_book`/`FeeSummaryService.summarize`, never a second
independently-implemented aggregation (S8 §6 edge case 4).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from flask import Blueprint, jsonify, request
from flask_login import current_user

from app.core.clock import MarketClock
from app.core.errors import NotFoundError, ValidationError
from app.core.pagination import decode_cursor, normalize_limit, paginate
from app.core.security import requires_role
from app.core.uow import SessionRole
from app.extensions import limiter
from app.models.marketdata.trading_calendar import CachedTradingCalendar
from app.services.admin.uow import AdminUnitOfWork
from app.services.fees.fee_summary_service import FeeSummaryService
from app.services.reconciliation.break_aging_service import BreakAgingService
from app.services.valuation.valuation_service import ValuationService
from app.views.admin_customers import (
    AdminCustomerDetailResponse,
    AdminCustomersListResponse,
    AdminCustomerSummaryResponse,
)
from app.views.fees import (
    DunningStateResponse,
    FeeChargeResponse,
    FeeSummaryResponse,
    HighWaterMarkResponse,
)
from app.views.reconciliation import BreakResponse
from app.views.valuation import BalanceResponse

if TYPE_CHECKING:
    from app.models.reconciliation.reconciliation_break import ReconciliationBreak

admin_customers_bp = Blueprint(
    "admin_customers", __name__, url_prefix="/api/v1/admin/customers"
)

_STAFF_ROLES = ("adviser", "admin")


def _parse_optional_limit(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError("limit must be an integer") from exc


def _decode_customer_cursor(raw: str) -> tuple[str, uuid.UUID]:
    decoded = decode_cursor(raw)
    if len(decoded) != 2 or not isinstance(decoded[0], str) or not isinstance(decoded[1], str):
        raise ValidationError("invalid pagination cursor")
    try:
        return decoded[0], uuid.UUID(decoded[1])
    except ValueError as exc:
        raise ValidationError("invalid pagination cursor") from exc


def _break_to_response(break_row: ReconciliationBreak, *, now: datetime) -> BreakResponse:
    age = BreakAgingService.age(break_row, now=now)
    return BreakResponse(
        id=break_row.id,
        break_type=break_row.break_type.value,
        customer_id=break_row.customer_id,
        expected=break_row.expected,
        actual=break_row.actual,
        opened_at=break_row.opened_at,
        age_seconds=int(age.total_seconds()),
        status=break_row.status.value,
        resolved_at=break_row.resolved_at,
        resolved_by=break_row.resolved_by,
        resolution_note=break_row.resolution_note,
    )


@admin_customers_bp.route("", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def list_customers() -> Any:
    query = (request.args.get("query") or "").strip()
    if not query:
        raise ValidationError("query is required")

    limit = normalize_limit(_parse_optional_limit(request.args.get("limit")))
    after: tuple[str, uuid.UUID] | None = None
    raw_cursor = request.args.get("cursor")
    if raw_cursor:
        after = _decode_customer_cursor(raw_cursor)

    with AdminUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        rows = uow.customers.search(query, limit=limit, after=after)
        page = paginate(rows, limit=limit, cursor_key=lambda c: (c.email, str(c.id)))

        view = AdminCustomersListResponse(
            customers=[
                AdminCustomerSummaryResponse(
                    id=str(customer.id),
                    email=customer.email,
                    kyc_status=customer.kyc_status.value,
                    account_approval_status=customer.account_approval_status.value,
                )
                for customer in page.items
            ],
            next_cursor=page.next_cursor,
        )

    return jsonify(view.model_dump(mode="json")), 200


@admin_customers_bp.route("/<uuid:customer_id>", methods=["GET"])
@limiter.limit("60 per minute")
@requires_role(*_STAFF_ROLES)
def get_customer(customer_id: uuid.UUID) -> Any:
    with AdminUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        customer = uow.customers.get_by_id(customer_id)
        if customer is None:
            raise NotFoundError(f"customer {customer_id} not found")

        clock = MarketClock(CachedTradingCalendar(uow.calendar_cache))
        as_of_date = clock.market_date(datetime.now(UTC))
        result = ValuationService(uow).value_book(customer_id, as_of_date)

        now = datetime.now(UTC)
        open_breaks = uow.reconciliation_breaks.list_open_for_customer(customer_id)

        view = AdminCustomerDetailResponse(
            id=str(customer.id),
            email=customer.email,
            kyc_status=customer.kyc_status.value,
            account_approval_status=customer.account_approval_status.value,
            balance=BalanceResponse(
                total_value=result.total_value,
                as_of_date=result.as_of_date,
                completeness=result.completeness,
            ),
            open_reconciliation_breaks=[
                _break_to_response(break_row, now=now) for break_row in open_breaks
            ],
        )

    return jsonify(view.model_dump(mode="json")), 200


@admin_customers_bp.route("/<uuid:customer_id>/fees", methods=["GET"])
@limiter.limit("30 per minute")
@requires_role(*_STAFF_ROLES)
def get_customer_fees(customer_id: uuid.UUID) -> Any:
    with AdminUnitOfWork(customer_id=None, role=SessionRole(current_user.role)) as uow:
        if uow.customers.get_by_id(customer_id) is None:
            raise NotFoundError(f"customer {customer_id} not found")

        summary = FeeSummaryService(uow).summarize(customer_id)

        hwm = summary.high_water_mark
        dunning = summary.dunning
        view = FeeSummaryResponse(
            accrual_to_date=summary.accrual_to_date,
            high_water_mark=(
                HighWaterMarkResponse(peak_value=hwm.peak_value, updated_at=hwm.updated_at)
                if hwm is not None
                else None
            ),
            charges=[
                FeeChargeResponse(
                    id=str(charge.id),
                    billing_period_start=charge.billing_period_start,
                    billing_period_end=charge.billing_period_end,
                    total_accrued=charge.total_accrued,
                    status=charge.status.value,
                    stripe_charge_id=charge.stripe_charge_id,
                )
                for charge in summary.charges
            ],
            dunning=(
                DunningStateResponse(
                    fee_charge_id=str(dunning.fee_charge_id),
                    attempt_number=dunning.attempt_number,
                    next_retry_at=dunning.next_retry_at,
                    max_attempts=dunning.max_attempts,
                    status=dunning.status.value,
                )
                if dunning is not None
                else None
            ),
        )

    return jsonify(view.model_dump(mode="json")), 200


__all__ = ["admin_customers_bp"]
