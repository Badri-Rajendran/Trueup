"""Chat aggregates (S11): `chat_session`, `chat_message`, `chat_tool_call`.

`ChatModelsUnitOfWork` is a models-only `UnitOfWork` mixin (S0 §5's extension mechanism).
"""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.chat.chat_message import ChatMessageRepository
from app.models.chat.chat_session import ChatSessionRepository
from app.models.chat.chat_tool_call import ChatToolCallRepository


class ChatModelsUnitOfWork(UnitOfWork):
    @cached_property
    def chat_sessions(self) -> ChatSessionRepository:
        return ChatSessionRepository(self)

    @cached_property
    def chat_messages(self) -> ChatMessageRepository:
        return ChatMessageRepository(self)

    @cached_property
    def chat_tool_calls(self) -> ChatToolCallRepository:
        return ChatToolCallRepository(self)


__all__ = ["ChatModelsUnitOfWork"]
