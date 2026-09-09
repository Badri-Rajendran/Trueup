"""Response schemas for `app/controllers/api/securities.py` -- the security catalogue backing a
future watchlist feature (unrelated frontend task). Explicit allow-list only, never a raw
`Security`/`DailyClose` entity -- `app/views/` may not import `app/models/`, enforced by
`lint-imports`'s `views-are-not-entities` contract. `DailyCloseSummaryResponse.source` is passed
through unmodified from `DailyClose.source` -- the exact provenance value `SimulatedBadge` renders,
never re-derived or hardcoded here.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from datetime import date  # noqa: TC003 -- Pydantic resolves field annotations eagerly.

from pydantic import BaseModel

from app.core.money import Price  # noqa: TC001 -- Pydantic resolves field annotations eagerly.


class DailyCloseSummaryResponse(BaseModel):
    price: Price
    market_date: date
    source: str
    status: str


class SecurityResponse(BaseModel):
    security_id: uuid.UUID
    symbol: str
    name: str
    asset_class: str
    last_close: DailyCloseSummaryResponse | None


class SecuritiesListResponse(BaseModel):
    securities: list[SecurityResponse]
    next_cursor: str | None


__all__ = ["DailyCloseSummaryResponse", "SecuritiesListResponse", "SecurityResponse"]
