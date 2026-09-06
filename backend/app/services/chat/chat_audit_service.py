"""Writes one `chat_tool_call` row per tool invocation, each in its own committed UoW (S11 §5.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.models.chat.chat_tool_call import (
    ChatToolCall,
    ChatToolCallRepository,
    ChatToolCallStatus,
    ChatToolName,
)

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from types import TracebackType

    from app.integrations.openai.llm_agent_port import SqlToolOutcome


class ChatAuditUnitOfWork(Protocol):
    """Satisfied by `ChatUnitOfWork`."""

    @property
    def chat_tool_calls(self) -> ChatToolCallRepository: ...

    def commit(self) -> None: ...

    def __enter__(self) -> ChatAuditUnitOfWork: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...


class ChatAuditService:
    def __init__(self, uow_factory: Callable[[], ChatAuditUnitOfWork]) -> None:
        self._uow_factory = uow_factory

    def record_tool_call(
        self,
        *,
        message_id: uuid.UUID,
        tool_name: str,
        sql_text: str | None,
        outcome: SqlToolOutcome,
        latency_ms: int,
    ) -> None:
        with self._uow_factory() as uow:
            uow.chat_tool_calls.add(
                ChatToolCall(
                    message_id=message_id,
                    tool_name=ChatToolName(tool_name),
                    sql_text=sql_text,
                    row_count=outcome.row_count if outcome.status == "success" else None,
                    latency_ms=latency_ms,
                    status=ChatToolCallStatus(outcome.status),
                )
            )
            uow.commit()


__all__ = ["ChatAuditService", "ChatAuditUnitOfWork"]
