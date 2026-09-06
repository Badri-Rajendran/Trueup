"""Response schemas for `app/controllers/admin/staff_api_tokens.py` (S13 §3.2).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`,
`lint-imports`'s `views-are-not-entities` contract). `token` is present on
`StaffApiTokenIssuedResponse` only -- the raw token is returned exactly once, at issue time, and
never appears on any other response shape in this module.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from datetime import datetime  # noqa: TC003

from pydantic import BaseModel


class StaffApiTokenIssuedResponse(BaseModel):
    """`POST /api/v1/admin/staff-api-tokens` -- the one and only time the raw token is returned."""

    id: uuid.UUID
    label: str
    token: str
    created_at: datetime


class StaffApiTokenSummaryResponse(BaseModel):
    """One row of `GET /api/v1/admin/staff-api-tokens` -- never the raw token or its hash."""

    id: uuid.UUID
    label: str
    created_at: datetime
    revoked_at: datetime | None


class StaffApiTokensListResponse(BaseModel):
    tokens: list[StaffApiTokenSummaryResponse]


__all__ = [
    "StaffApiTokenIssuedResponse",
    "StaffApiTokenSummaryResponse",
    "StaffApiTokensListResponse",
]
