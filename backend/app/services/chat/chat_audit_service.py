"""`ChatAuditService` (S11 §3/§5.2 step 4, FR-53) — writes one `chat_tool_call` row per tool
invocation, committed independently of the turn's own outcome.

**Why this owns a `UnitOfWork` factory, not a single injected `UnitOfWork`.** S11 §5.2 step 4 is
explicit: "each tool call is recorded ... as it happens, not batched at the end — so a turn that
fails partway through still leaves an audit trail." A single `UnitOfWork` per HTTP request (S0
§5's normal shape) cannot honor that -- if the turn's own transaction later rolls back, every
audit row written on it rolls back too. Each `record_tool_call()` call therefore opens, commits,
and closes its own short-lived `UnitOfWork` via the injected factory, so an audit write survives
independently of whatever happens for the rest of the turn.
"""

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
    """The structural dependency this service needs -- `ChatUnitOfWork` satisfies it."""

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
