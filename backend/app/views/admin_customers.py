"""Response schemas for `app/controllers/admin/customers.py` (S8 §4 rows 1/2/6).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`,
`lint-imports`'s `views-are-not-entities` contract). `AdminCustomerDetailResponse.balance` reuses
`BalanceResponse` verbatim (never a second, independently-shaped balance field) so the JSON this
route emits is structurally identical to `GET /valuation/balance`'s -- the same "one code path,
one figure" guarantee S8 §6 edge case 4 requires, made a type-level fact rather than a convention
two authors could let drift.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.views.reconciliation import BreakResponse  # noqa: TC001
from app.views.valuation import BalanceResponse  # noqa: TC001


class AdminCustomerSummaryResponse(BaseModel):
    """One row of `GET /api/v1/admin/customers` (S8 §4 row 1)."""

    id: str
    email: str
    kyc_status: str
    account_approval_status: str


class AdminCustomersListResponse(BaseModel):
    customers: list[AdminCustomerSummaryResponse]
    next_cursor: str | None


class AdminCustomerDetailResponse(BaseModel):
    """`GET /api/v1/admin/customers/<id>` (S8 §4 row 2) -- `open_reconciliation_breaks` is
    non-empty exactly when S8 §6 edge case 2 applies, surfacing it directly on the aggregated
    view rather than only on the dedicated breaks screen."""

    id: str
    email: str
    kyc_status: str
    account_approval_status: str
    balance: BalanceResponse
    open_reconciliation_breaks: list[BreakResponse]


__all__ = [
    "AdminCustomerDetailResponse",
    "AdminCustomerSummaryResponse",
    "AdminCustomersListResponse",
]
