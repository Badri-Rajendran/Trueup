"""Response schemas for `app/controllers/admin/rebalance.py` (foundation spec §13's routing
table: "S9 | admin/rebalance.py (visibility only)").

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, field_serializer

from app.core.money import Money  # noqa: TC001 -- Pydantic resolves field annotations eagerly.


class DriftHoldingResponse(BaseModel):
    """One evaluated holding -- `security_id`/`symbol` are both `None` for the implicit CASH
    entry (S9 §4's last line). Every holding is included, flagged or not, so an adviser sees
    "how close," not just which ones would trade (`DriftEvaluationService.DriftEntry`'s own
    docstring)."""

    security_id: uuid.UUID | None
    symbol: str | None
    current_market_value: Money
    target_market_value: Money
    current_weight_pct: Decimal
    target_weight_pct: Decimal
    is_flagged: bool
    direction: Literal["buy", "sell"]

    @field_serializer("current_weight_pct", "target_weight_pct", when_used="json")
    def _serialize_weight_pct(self, value: Decimal) -> str:
        """Plain fixed-point, matching `ReturnsResponse.twr`'s precedent for a ratio field."""
        return format(value, "f")


class RebalanceStatusResponse(BaseModel):
    """`GET /api/v1/admin/rebalance/<customer_id>` -- read-only drift status as of today; never
    generates an order (rebalancing itself is system-initiated by `MonthlyRebalanceJob`, per the
    foundation spec's own row: "visibility only")."""

    customer_id: uuid.UUID
    model_portfolio_id: uuid.UUID | None
    as_of_date: date
    completeness: Literal["complete", "partial"]
    total_value: Money
    holdings: list[DriftHoldingResponse]


__all__ = ["DriftHoldingResponse", "RebalanceStatusResponse"]
