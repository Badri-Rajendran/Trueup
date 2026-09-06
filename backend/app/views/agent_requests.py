"""Response schemas for `app/controllers/admin/agent_requests.py` (S13 §5).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`,
`lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from datetime import datetime  # noqa: TC003
from typing import Any, Literal

from pydantic import BaseModel

AgentActionTypeLiteral = Literal["resolve_break", "kyc_override", "rebalance"]
AgentActionStatusLiteral = Literal[
    "pending", "approved", "rejected", "executed", "execution_failed"
]


class AgentActionRequestResponse(BaseModel):
    """One `agent_action_request` row (S13 §3.1)."""

    id: uuid.UUID
    action: AgentActionTypeLiteral
    arguments: dict[str, Any]
    requesting_agent: str
    justification: str
    status: AgentActionStatusLiteral
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    review_note: str | None
    execution_error: str | None
    executed_at: datetime | None
    created_at: datetime


class AgentActionRequestsListResponse(BaseModel):
    """`GET /api/v1/admin/agent-requests` (S13 §5) -- keyset-paginated, oldest-first."""

    requests: list[AgentActionRequestResponse]
    next_cursor: str | None


__all__ = [
    "AgentActionRequestResponse",
    "AgentActionRequestsListResponse",
    "AgentActionStatusLiteral",
    "AgentActionTypeLiteral",
]
