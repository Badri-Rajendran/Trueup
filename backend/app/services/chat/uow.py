"""UoW for S11's chat aggregate (`chat_session`/`chat_message`/`chat_tool_call`). Runs under `DbRole.APP`."""

from __future__ import annotations

from app.models.chat import ChatModelsUnitOfWork


class ChatUnitOfWork(ChatModelsUnitOfWork):
    pass


__all__ = ["ChatUnitOfWork"]
