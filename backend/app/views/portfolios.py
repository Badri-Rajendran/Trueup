"""Response schemas for `app/controllers/api/portfolios.py` (S8 §3, "Owning spec: S9 §3").

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date  # noqa: TC003
from decimal import Decimal  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, field_serializer

from app.core.money import Money, Price, Units  # noqa: TC001 -- Pydantic resolves eagerly.


class TargetWeightResponse(BaseModel):
    security_id: uuid.UUID
    symbol: str
    weight_pct: Decimal

    @field_serializer("weight_pct", when_used="json")
    def _serialize_weight_pct(self, value: Decimal) -> str:
        """Plain fixed-point, matching `ReturnsResponse.twr`'s identical precedent -- a JSON
        number is IEEE-754 and lossy, and this codebase never puts a financial ratio on the wire
        as one (root `CLAUDE.md`, ADR 16's spirit applied to a plain `Decimal` ratio field)."""
        return format(value, "f")


class ModelPortfolioResponse(BaseModel):
    """`GET /api/v1/portfolios/models` (S8 §3): one of the four model portfolios' public
    descriptions -- name plus its full target-weight breakdown."""

    id: uuid.UUID
    name: str
    target_weights: list[TargetWeightResponse]


class ModelPortfolioListResponse(BaseModel):
    models: list[ModelPortfolioResponse]


class AssignmentResponse(BaseModel):
    """`GET, POST /api/v1/portfolios/assignment` (S8 §3, FR-7)."""

    customer_id: uuid.UUID
    model_portfolio_id: uuid.UUID
    assigned_at: date


class CurrentAssignmentResponse(BaseModel):
    """`GET /api/v1/portfolios/assignment` -- `assignment` is `None` for a customer who has not
    yet chosen a model, never a 404 (choosing is the very action this same route's `POST` exists
    for)."""

    assignment: AssignmentResponse | None


class HoldingResponse(BaseModel):
    """One line of `GET /api/v1/portfolios/holdings` (Portfolio page redesign, ADR 26 context) --
    `security_id`/`symbol`/`units`/`price` are all `None` for the implicit CASH line
    (`DriftEntry`'s own convention, S9 §4). A security the customer holds but that has dropped out
    of their assigned model still appears here with `target_weight_pct: 0`."""

    security_id: uuid.UUID | None
    symbol: str | None
    units: Units | None
    price: Price | None
    market_value: Money
    current_weight_pct: Decimal
    target_weight_pct: Decimal
    drift_pct: Decimal
    is_flagged: bool

    @field_serializer("current_weight_pct", "target_weight_pct", "drift_pct", when_used="json")
    def _serialize_pct(self, value: Decimal) -> str:
        """Plain fixed-point, matching `TargetWeightResponse`'s own precedent for a ratio field."""
        return format(value, "f")


class PortfolioHoldingsResponse(BaseModel):
    """`GET /api/v1/portfolios/holdings` -- live, as-of-today holdings against the customer's
    assigned model. `completeness` must survive to the wire unchanged (NFR-6): `"partial"` is
    never presented as an empty holdings list."""

    customer_id: uuid.UUID
    as_of_date: date
    completeness: Literal["complete", "partial"]
    total_value: Money
    holdings: list[HoldingResponse]


class PerformancePointResponse(BaseModel):
    as_of_date: date
    value: Money


class PortfolioPerformanceResponse(BaseModel):
    """`GET /api/v1/portfolios/performance` (ADR 26) -- the live, as-of-now performance series.
    Always `watermark_type: 'live'`; `GET /api/v1/statements`'s `StatementDetailResponse` carries
    the as-published counterpart and is never confused with this one."""

    customer_id: uuid.UUID
    range: Literal["1m", "3m", "6m", "1y", "all"]
    period_start: date | None
    period_end: date
    cumulative_twr: Decimal
    is_provisional: bool
    points: list[PerformancePointResponse]
    watermark_type: Literal["live"] = "live"

    @field_serializer("cumulative_twr", when_used="json")
    def _serialize_twr(self, value: Decimal) -> str:
        """Plain fixed-point, matching `ReturnsResponse.twr`'s identical precedent."""
        return format(value, "f")


__all__ = [
    "AssignmentResponse",
    "CurrentAssignmentResponse",
    "HoldingResponse",
    "ModelPortfolioListResponse",
    "ModelPortfolioResponse",
    "PerformancePointResponse",
    "PortfolioHoldingsResponse",
    "PortfolioPerformanceResponse",
    "TargetWeightResponse",
]
