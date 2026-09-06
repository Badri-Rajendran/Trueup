"""Response schemas for `app/controllers/api/breaks.py` (S7 §8).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`, enforced
by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from datetime import datetime  # noqa: TC003
from typing import Any, Literal

from pydantic import BaseModel


class BreakResponse(BaseModel):
    """One `reconciliation_break` row, plus `age_seconds` (S7 §7's aging indicator, computed on
    read, never stored)."""

    id: uuid.UUID
    break_type: str
    customer_id: uuid.UUID | None
    expected: dict[str, Any] | None
    actual: dict[str, Any] | None
    opened_at: datetime
    age_seconds: int
    status: Literal["open", "resolved"]
    resolved_at: datetime | None
    resolved_by: uuid.UUID | None
    resolution_note: str | None


class BreaksListResponse(BaseModel):
    """`GET /api/v1/admin/breaks?status=open` (S7 §8) — sorted oldest-first (S7 §7)."""

    breaks: list[BreakResponse]


__all__ = ["BreakResponse", "BreaksListResponse"]
