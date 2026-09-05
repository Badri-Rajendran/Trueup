"""Response schemas for `app/controllers/api/funding.py` (S2 §6, OWASP API3).

Explicit allow-lists only -- `plaid_access_token` never reaches a response body (root `CLAUDE.md`),
and `app/views/` may not import `app/models/` (enforced by `lint-imports`).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date, datetime  # noqa: TC003

from pydantic import BaseModel


class BankLinkResponse(BaseModel):
    id: uuid.UUID
    status: str
    linked_at: datetime


class DepositResponse(BaseModel):
    journal_entry_id: uuid.UUID
    settlement_obligation_id: uuid.UUID
    expected_settlement_date: date


class WithdrawalResponse(BaseModel):
    journal_entry_id: uuid.UUID
    destination_bank_link_id: uuid.UUID
