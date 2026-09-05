"""Response schemas for `app/controllers/api/funding.py` (S2 §6, OWASP API3).

Explicit allow-lists only -- `plaid_access_token` never reaches a response body (root `CLAUDE.md`),
and `app/views/` may not import `app/models/` (enforced by `lint-imports`).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel


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
