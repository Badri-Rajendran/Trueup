"""Response schemas for `app/controllers/api/funding.py` (S2 §6, OWASP API3).

Explicit allow-lists only -- `plaid_access_token` never reaches a response body (root `CLAUDE.md`),
and `app/views/` may not import `app/models/` (enforced by `lint-imports`).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel

from app.core.money import Money  # noqa: TC001 -- Pydantic needs the real type at class-build time.


class CashSummaryResponse(BaseModel):
    """`GET /api/v1/funding/cash-summary` -- `CashPolicyService.withdrawable`/`.investable`
    (S1 §5, ADR 5), never merged into one figure (frontend design-system §8.2: two equal-weight
    stat figures, load-bearing). `withdrawable` is confirmed-settled cash minus holds only;
    `investable` additionally counts unsettled inflows -- the asymmetry is deliberate (ADR 5),
    not a bug, and both must reach the client exactly as computed, never merged into one number.

    `outstanding_receivable` is the balance owed after a bounced deposit (S2 §5.2 step 4, FR-6 --
    "the customer-facing surface must show this as an outstanding balance the customer needs to
    cover"); it is `0.0000`, never `null`, for every customer who's never had a deposit returned
    (the overwhelming majority). The three cap fields exist so the client can show real headroom
    and validate before submitting rather than only reacting to a 422."""

    withdrawable: Money
    investable: Money
    outstanding_receivable: Money
    deposit_cap_per_transaction: Money
    deposit_cap_per_day: Money
    deposited_today: Money


class FundingHistoryEntryResponse(BaseModel):
    """One deposit or withdrawal, carrying the SIGNED cash-leg amount (positive for a deposit,
    negative for a withdrawal) -- one row per movement, never one per posting.

    `settlement_status` is nullable by design: a withdrawal carries no settlement obligation, so
    its `settlement_status`, `expected_settlement_date`, and `failure_reason` are all `null`
    rather than a fabricated value asserting a custodial confirmation that never happened.
    `entry_type`/`settlement_status` are plain `str` here, as `BankLinkResponse.status` already
    is; the controller passes `.value`."""

    journal_entry_id: uuid.UUID
    entry_type: str
    effective_date: date
    recorded_at: datetime
    amount: Money
    settlement_status: str | None
    expected_settlement_date: date | None
    failure_reason: str | None


class FundingHistoryResponse(BaseModel):
    """`GET /api/v1/funding/history` -- deposits and withdrawals, most-recent-first."""

    entries: list[FundingHistoryEntryResponse]


class LinkTokenResponse(BaseModel):
    """`POST /api/v1/funding/link-token` — what Plaid Link's client SDK needs to open at all,
    before a caller has a `public_token` to hand `POST /bank-links`."""

    link_token: str
    expiration: datetime


class BankLinkResponse(BaseModel):
    id: uuid.UUID
    status: str
    linked_at: datetime


class CurrentBankLinkResponse(BaseModel):
    """`GET /api/v1/funding/bank-links/current` -- the customer's not-yet-`superseded` link
    (`active` or `requires_reauth`, `BankLinkRepository.current_for_customer`'s own definition of
    "current"), or `None` if they've never linked one. Onboarding and the funding screen both need
    this same "is a bank already linked" fact and had no way to ask it (frontend escalation)."""

    bank_link: BankLinkResponse | None


class DepositResponse(BaseModel):
    journal_entry_id: uuid.UUID
    settlement_obligation_id: uuid.UUID
    expected_settlement_date: date


class WithdrawalResponse(BaseModel):
    journal_entry_id: uuid.UUID
    destination_bank_link_id: uuid.UUID
