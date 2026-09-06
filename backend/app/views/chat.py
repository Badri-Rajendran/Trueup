"""Response/stream-event schemas for `app/controllers/api/chat.py` (S11 §6).

Explicit allow-lists only, never a raw entity or a service-layer dataclass (`app/views/` may not
import `app/models/` or `app/services/`, `lint-imports`'s `views-are-not-entities` contract) --
the controller converts `ChatStreamEvent`/`ChatMessage` into these schemas before serializing.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 -- Pydantic resolves field annotations eagerly.
from typing import Literal
from uuid import UUID  # noqa: TC003

from pydantic import BaseModel


class ChatSessionCreatedResponse(BaseModel):
    session_id: UUID


class ChatSessionSummaryResponse(BaseModel):
    id: UUID
    status: str
    created_at: datetime


class ChatSessionsListResponse(BaseModel):
    sessions: list[ChatSessionSummaryResponse]


class ChatMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class ChatMessagesListResponse(BaseModel):
    messages: list[ChatMessageResponse]


class ChatToolCallSummaryView(BaseModel):
    tool_name: str
    summary: str


class ChatStreamTokenEvent(BaseModel):
    """SSE `data:` payload for a streaming token chunk."""

    type: Literal["token"] = "token"
    text: str


class ChatStreamCompletedEvent(BaseModel):
    """SSE `data:` payload for the one terminal "success" event per turn (S11 §6) -- a structured
    trace of what was checked, never raw SQL by default."""

    type: Literal["completed"] = "completed"
    message_id: UUID
    tool_calls: list[ChatToolCallSummaryView]


class ChatStreamErrorEvent(BaseModel):
    """SSE `data:` payload for the one terminal "failure" event per turn (S11 §5.3)."""

    type: Literal["error"] = "error"
    message: str


__all__ = [
    "ChatMessageResponse",
    "ChatMessagesListResponse",
    "ChatSessionCreatedResponse",
    "ChatSessionSummaryResponse",
    "ChatSessionsListResponse",
    "ChatStreamCompletedEvent",
    "ChatStreamErrorEvent",
    "ChatStreamTokenEvent",
    "ChatToolCallSummaryView",
]
