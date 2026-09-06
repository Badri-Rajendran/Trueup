"""`LlmAgentPort` (S11 §3, ADR 18) — the only interface `app/services/chat/` depends on for the LLM
call. `ChatToolContext` carries two plain callables (`get_schema`/`execute_sql`) supplied by
`ChatOrchestrationService`; the port and its adapters never know what those callables actually do
(ADR 19's security boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class SqlToolOutcome:
    """What `execute_sql` hands back — never a raw exception (S11 §5.3's error table)."""

    status: str
    """One of `chat_tool_call_status`'s values: success / validator_rejected / timeout / error."""
    rows: tuple[dict[str, str], ...] = ()
    row_count: int = 0
    message: str = ""
    """Populated for every non-`success` status — customer-safe, never a raw Postgres error (OWASP A05)."""


@dataclass(frozen=True, slots=True)
class ChatToolContext:
    """Per-turn callbacks the agent's two function tools invoke. See module docstring."""

    get_schema: Callable[[], str]
    execute_sql: Callable[[str], SqlToolOutcome]
    on_tool_call: Callable[[str, str | None, SqlToolOutcome, int], None]
    """`(tool_name, sql_text, outcome, latency_ms) -> None`, called once per tool invocation so
    `ChatAuditService` records it when it happens (S11 §5.2 step 4)."""


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One prior turn of history fed back to the model. `role` matches `chat_message.role` (S11 §3)."""

    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ToolCallSummary:
    """S11 §6's structured trace — `{tool_name, summary}`, never raw SQL by default."""

    tool_name: str
    summary: str


@dataclass(frozen=True, slots=True)
class ChatTokenEvent:
    text: str


@dataclass(frozen=True, slots=True)
class ChatCompletedEvent:
    final_text: str
    tool_calls: tuple[ToolCallSummary, ...]


@dataclass(frozen=True, slots=True)
class ChatErrorEvent:
    """S11 §5.3: outage/timeout closes the SSE stream with an explicit error, never a silent hang."""

    message: str


ChatStreamEvent = ChatTokenEvent | ChatCompletedEvent | ChatErrorEvent


class LlmAgentPort(Protocol):
    def run_turn(
        self,
        *,
        system_prompt: str,
        history: Sequence[ConversationTurn],
        message: str,
        tool_context: ChatToolContext,
        max_tool_iterations: int,
    ) -> Iterator[ChatStreamEvent]:
        """Runs one turn bounded by `max_tool_iterations` (S11 §5.2 step 3, NFR-16). Yields zero or
        more `ChatTokenEvent`s, then exactly one terminal event."""
        ...


__all__ = [
    "ChatCompletedEvent",
    "ChatErrorEvent",
    "ChatStreamEvent",
    "ChatTokenEvent",
    "ChatToolContext",
    "ConversationTurn",
    "LlmAgentPort",
    "SqlToolOutcome",
    "ToolCallSummary",
]
