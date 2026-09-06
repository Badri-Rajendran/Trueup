"""`LlmAgentPort` (S11 §3, ADR 18) — the only interface `app/services/chat/` depends on for the
LLM call. `OpenAIAgentAdapter` (real) and `FakeAgentAdapter` (contract tests, no network) both
satisfy this structurally, run against the identical contract suite (`tests/contract/`).

**`ChatToolContext` is deliberately dumb.** It carries two plain callables the adapter's function
tools invoke — `get_schema`/`execute_sql` — supplied by `ChatOrchestrationService`, which is the
only code that knows about `sql_tool_validator`, the `chat_readonly` connection, or
`ChatAuditService`. The port and its adapters never import any of those; a fake test can hand the
adapter trivial stub callables with no database at all. This is the seam ADR 19's boundary sits
behind: whatever the model decides to call, it can only ever reach these two callables, and what
those callables actually do is entirely `ChatOrchestrationService`'s decision, not the agent's.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence


@dataclass(frozen=True, slots=True)
class SqlToolOutcome:
    """What `execute_sql` hands back to the tool call — never a raw exception, always one of these
    four shapes (S11 §5.3's error table)."""

    status: str
    """One of `chat_tool_call_status`'s values: success / validator_rejected / timeout / error."""
    rows: tuple[dict[str, str], ...] = ()
    row_count: int = 0
    message: str = ""
    """Populated for every non-`success` status — a structured, customer-safe explanation the
    agent can react to conversationally, never a raw Postgres error string (OWASP A05)."""


@dataclass(frozen=True, slots=True)
class ChatToolContext:
    """Per-turn callbacks the agent's two function tools invoke. See module docstring."""

    get_schema: Callable[[], str]
    execute_sql: Callable[[str], SqlToolOutcome]
    on_tool_call: Callable[[str, str | None, SqlToolOutcome, int], None]
    """`(tool_name, sql_text, outcome, latency_ms) -> None` — called once per tool invocation, from
    inside the tool function itself, so `ChatAuditService` records it exactly when it happens
    (S11 §5.2 step 4), not reconstructed afterward from the stream."""


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One prior turn of history fed back to the model as context. `role` is `"user"` or
    `"assistant"`, matching `chat_message.role` (S11 §3)."""

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
    """S11 §5.3: "OpenAI API outage/timeout: SSE stream closes with an explicit error event, never
    a silent hang." `message` is always customer-safe."""

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
        """Runs exactly one turn: `message` plus `history` as context, bounded by
        `max_tool_iterations` tool-calling round trips (S11 §5.2 step 3, NFR-16). Yields zero or
        more `ChatTokenEvent`s as they stream, then exactly one terminal event — a
        `ChatCompletedEvent` or a `ChatErrorEvent` — never both, and never neither."""
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
