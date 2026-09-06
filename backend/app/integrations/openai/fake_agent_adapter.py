"""`FakeAgentAdapter` — the `LlmAgentPort` fake for `tests/contract/`, no network call (ADR 18).

Script-driven, not content-driven: a queued turn's tool-call sequence and final answer are fixed
at `queue_turn()` time and never branch on tool-result content — proves tool results are opaque
data, never re-parsed as commands, independent of any real model's behavior (ADR 19).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.integrations.openai.llm_agent_port import (
    ChatCompletedEvent,
    ChatErrorEvent,
    ChatTokenEvent,
    SqlToolOutcome,
    ToolCallSummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from app.integrations.openai.llm_agent_port import (
        ChatStreamEvent,
        ChatToolContext,
        ConversationTurn,
    )


@dataclass(frozen=True, slots=True)
class FakeToolCall:
    """One scripted tool invocation. `sql` is ignored for `get_database_schema`."""

    tool_name: str
    sql: str | None = None


@dataclass(slots=True)
class _QueuedTurn:
    tool_calls: list[FakeToolCall] = field(default_factory=list)
    final_text: str = ""


class FakeAgentAdapter:
    """Implements `LlmAgentPort` (structural -- no inheritance required)."""

    def __init__(self) -> None:
        self._queue: list[_QueuedTurn] = []

    def queue_turn(self, *, tool_calls: Sequence[FakeToolCall] = (), final_text: str) -> None:
        """Schedules the next `run_turn()` call's fixed behavior. Consumed FIFO."""
        self._queue.append(_QueuedTurn(tool_calls=list(tool_calls), final_text=final_text))

    def run_turn(
        self,
        *,
        system_prompt: str,
        history: Sequence[ConversationTurn],
        message: str,
        tool_context: ChatToolContext,
        max_tool_iterations: int,
    ) -> Iterator[ChatStreamEvent]:
        del system_prompt, history, message  # unused by a scripted fake
        if not self._queue:
            raise AssertionError(
                "FakeAgentAdapter.run_turn() called with no queued turn -- call queue_turn() "
                "first in the test that drives it"
            )
        turn = self._queue.pop(0)

        if len(turn.tool_calls) > max_tool_iterations:
            yield ChatErrorEvent(
                message="the assistant needed more steps than this turn allows; please rephrase"
            )
            return

        summaries: list[ToolCallSummary] = []
        for call in turn.tool_calls:
            start = time.monotonic()
            if call.tool_name == "get_database_schema":
                schema = tool_context.get_schema()
                latency_ms = int((time.monotonic() - start) * 1000)
                outcome = SqlToolOutcome(status="success", message=schema)
                tool_context.on_tool_call(call.tool_name, None, outcome, latency_ms)
                summaries.append(
                    ToolCallSummary(tool_name=call.tool_name, summary="fetched the curated schema")
                )
            else:
                outcome = tool_context.execute_sql(call.sql or "")
                latency_ms = int((time.monotonic() - start) * 1000)
                tool_context.on_tool_call(call.tool_name, call.sql, outcome, latency_ms)
                summaries.append(
                    ToolCallSummary(
                        tool_name=call.tool_name,
                        summary=f"{outcome.status}, {outcome.row_count} row(s)",
                    )
                )

        for word in turn.final_text.split(" "):
            yield ChatTokenEvent(text=f"{word} ")
        yield ChatCompletedEvent(final_text=turn.final_text, tool_calls=tuple(summaries))


__all__ = ["FakeAgentAdapter", "FakeToolCall"]
