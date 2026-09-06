"""Response schemas for `app/controllers/api/portfolios.py` (S8 §3, "Owning spec: S9 §3").

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time.
from datetime import date  # noqa: TC003
from decimal import Decimal  # noqa: TC003

from pydantic import BaseModel, field_serializer


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


__all__ = [
    "AssignmentResponse",
    "CurrentAssignmentResponse",
    "ModelPortfolioListResponse",
    "ModelPortfolioResponse",
    "TargetWeightResponse",
]
