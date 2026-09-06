"""Response schemas for `app/controllers/api/statements.py` (S6 §8).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`,
`lint-imports`'s `views-are-not-entities` contract). Every figure here is `watermark_type:
'as_published'` (S6 §7) -- the live/as-corrected variant is `app/views/valuation.py`'s
`ReturnsResponse`/`BalanceResponse`, never this module's.
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from decimal import Decimal  # noqa: TC003
from typing import Any, Literal

from pydantic import BaseModel, field_serializer

from app.core.money import Money  # noqa: TC001 -- Pydantic resolves field annotations eagerly.


class StatementSummaryResponse(BaseModel):
    """One row of `GET /api/v1/statements` (S6 §8) -- carries the `publish_watermark` handle S6
    §7 requires for a caller to later ask for this exact figure again, forever."""

    period_start: date
    period_end: date
    publish_watermark: datetime
    twr: Decimal
    balance: Money

    @field_serializer("twr", when_used="json")
    def _serialize_twr(self, value: Decimal) -> str:
        """Plain fixed-point, matching `ReturnsResponse`'s own reasoning (never `0E-10`-style
        scientific notation for `sub_period_return.return_pct`'s NUMERIC(18,10) scale)."""
        return format(value, "f")


class StatementsListResponse(BaseModel):
    statements: list[StatementSummaryResponse]


class StatementDetailResponse(BaseModel):
    """`GET /api/v1/statements/<period>` (S6 §8) -- the published snapshot's figures, always
    `watermark_type: 'as_published'` (S6 §7)."""

    period_start: date
    period_end: date
    publish_watermark: datetime
    published_at: datetime
    twr: Decimal
    balance: Money
    holdings: dict[str, Any]
    watermark_type: Literal["as_published"] = "as_published"

    @field_serializer("twr", when_used="json")
    def _serialize_twr(self, value: Decimal) -> str:
        return format(value, "f")


__all__ = ["StatementDetailResponse", "StatementSummaryResponse", "StatementsListResponse"]
