"""Response schemas for `app/controllers/api/valuation.py` (S4 §7/§9).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract). `completeness`/`is_provisional` are carried
through unchanged from the service layer — S4 §9 calls out a contract test proving this flag is
never dropped between `ValuationService`/`TwrService` and the response body.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from decimal import Decimal  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, field_serializer

from app.core.money import (  # noqa: TC001 -- Pydantic resolves field annotations eagerly.
    Money,
    Units,
)


class BalanceResponse(BaseModel):
    """`GET /api/v1/valuation/balance` (S4 §7, FR-18)."""

    total_value: Money
    as_of_date: date
    completeness: Literal["complete", "partial"]


class ReturnsResponse(BaseModel):
    """`GET /api/v1/valuation/returns` (S4 §7, FR-16/FR-17) — always the live TWR; S6 owns the
    as-published variant."""

    twr: Decimal
    period_start: date
    period_end: date
    is_provisional: bool

    @field_serializer("twr", when_used="json")
    def _serialize_twr(self, value: Decimal) -> str:
        """Plain fixed-point, never Python's `0E-10`-style scientific notation for a zero
        return at `sub_period_return.return_pct`'s NUMERIC(18,10) scale (Python's `Decimal.__str__`
        switches to exponential form once the exponent passes -6)."""
        return format(value, "f")


class HistoryEntryResponse(BaseModel):
    entry_type: str
    effective_date: date
    recorded_at: datetime
    amount_money: Money | None
    quantity_units: Units | None
    memo: str | None


class HistoryResponse(BaseModel):
    """`GET /api/v1/valuation/history` (S4 §7, FR-18) — live by default (ADR 6)."""

    entries: list[HistoryEntryResponse]


__all__ = ["BalanceResponse", "HistoryEntryResponse", "HistoryResponse", "ReturnsResponse"]
