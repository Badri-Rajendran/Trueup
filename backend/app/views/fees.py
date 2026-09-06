"""Response schemas for `app/controllers/api/fees.py` (S10 §7).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 -- Pydantic resolves field annotations eagerly.

from pydantic import BaseModel

from app.core.money import Money  # noqa: TC001 -- Pydantic resolves field annotations eagerly.


class HighWaterMarkResponse(BaseModel):
    peak_value: Money
    updated_at: datetime


class FeeChargeResponse(BaseModel):
    id: str
    billing_period_start: date
    billing_period_end: date
    total_accrued: Money
    status: str
    stripe_charge_id: str | None


class DunningStateResponse(BaseModel):
    fee_charge_id: str
    attempt_number: int
    next_retry_at: datetime
    max_attempts: int
    status: str


class FeeSummaryResponse(BaseModel):
    """`GET /api/v1/fees` (S10 §7) -- accrual-to-date (the live, not-yet-charged running total for
    the open billing period), the current high-water-mark, the full charge history, and the
    current `dunning`/`exhausted` state if any."""

    accrual_to_date: Money
    high_water_mark: HighWaterMarkResponse | None
    charges: list[FeeChargeResponse]
    dunning: DunningStateResponse | None


class PaymentMethodResponse(BaseModel):
    stripe_payment_method_id: str
    updated_at: datetime


__all__ = [
    "DunningStateResponse",
    "FeeChargeResponse",
    "FeeSummaryResponse",
    "HighWaterMarkResponse",
    "PaymentMethodResponse",
]
