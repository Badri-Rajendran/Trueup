"""`OpenAIAgentAdapter` — the real `LlmAgentPort` implementation (ADR 18): OpenAI's Agent SDK,
native function-tool calling, native streaming.

**Sync-to-async bridge.** `Runner.run_streamed()` starts its run as a background `asyncio` task
the moment it is called, so it must be called from inside a running event loop -- but every Flask
view in this codebase is synchronous (S0 §3), and `LlmAgentPort.run_turn()` is a plain generator so
`ChatOrchestrationService` can drive an SSE response with an ordinary `for` loop. `_run_in_thread`
below is the seam: a dedicated background thread owns the one event loop for this turn, drains
`RunResultStreaming.stream_events()` inside it, and relays each event to the calling thread through
a plain `queue.Queue` -- the same "confine async to a thread, cross back with a thread-safe queue"
shape used to bridge any async-native SDK into a sync generator, with no partial/half-drained loop
left behind once the turn ends.

**Tool wiring.** `_get_database_schema_tool`/`_execute_read_only_sql_tool` are the two function
tools ADR 18 names. Both are thin: they call back into whatever `ChatToolContext` the orchestration
service supplied (`ctx.context`) and record the invocation via `on_tool_call` before returning --
this module has no idea what `chat_readonly`, the validator, or the audit log are (S0 §3's
dependency rule); it only knows the two-callable shape `llm_agent_port.py` defines.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import queue
import threading
import time
from typing import TYPE_CHECKING, Any

from agents import (
    Agent,
    RawResponsesStreamEvent,
    RunContextWrapper,
    Runner,
    function_tool,
    set_default_openai_client,
)
from openai import AsyncOpenAI

from app.core.logging import get_logger
from app.integrations.openai.llm_agent_port import (
    ChatCompletedEvent,
    ChatErrorEvent,
    ChatTokenEvent,
    ChatToolContext,
    SqlToolOutcome,
    ToolCallSummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from app.integrations.openai.llm_agent_port import ChatStreamEvent, ConversationTurn

log = get_logger(__name__)

_SENTINEL = object()


@function_tool(name_override="get_database_schema")
async def _get_database_schema_tool(ctx: RunContextWrapper[ChatToolContext]) -> str:
    """Returns the column list of every curated view this assistant may query."""
    start = time.monotonic()
    schema = ctx.context.get_schema()
    latency_ms = int((time.monotonic() - start) * 1000)
    ctx.context.on_tool_call(
        "get_database_schema", None, SqlToolOutcome(status="success", message=schema), latency_ms
    )
    return schema


@function_tool(name_override="execute_read_only_sql")
async def _execute_read_only_sql_tool(ctx: RunContextWrapper[ChatToolContext], sql: str) -> str:
    """Executes one read-only SELECT against the curated views and returns the rows as JSON.

    `sql` must reference only the views named in `get_database_schema`'s output. A rejected or
    failed query returns a JSON `{"error": ...}` body, never a raw database error string.
    """
    start = time.monotonic()
    outcome = ctx.context.execute_sql(sql)
    latency_ms = int((time.monotonic() - start) * 1000)
    ctx.context.on_tool_call("execute_read_only_sql", sql, outcome, latency_ms)
    if outcome.status != "success":
        return json.dumps({"error": outcome.message})
    return json.dumps({"rows": [dict(row) for row in outcome.rows], "row_count": outcome.row_count})


def _summarize(tool_name: str, outcome: SqlToolOutcome) -> str:
    if tool_name == "get_database_schema":
        return "fetched the curated schema"
    if outcome.status == "success":
        return f"queried the curated views, {outcome.row_count} row(s)"
    return f"query {outcome.status}"


class OpenAIAgentAdapter:
    """Implements `LlmAgentPort` (structural -- no inheritance required)."""

    def __init__(self, *, api_key: str, org_id: str | None, model: str) -> None:
        set_default_openai_client(AsyncOpenAI(api_key=api_key, organization=org_id))
        self._model = model

    def run_turn(
        self,
        *,
        system_prompt: str,
        history: Sequence[ConversationTurn],
        message: str,
        tool_context: ChatToolContext,
        max_tool_iterations: int,
    ) -> Iterator[ChatStreamEvent]:
        event_queue: queue.Queue[ChatStreamEvent | object] = queue.Queue()

        thread = threading.Thread(
            target=self._run_in_thread,
            args=(system_prompt, history, message, tool_context, max_tool_iterations, event_queue),
            daemon=True,
        )
        thread.start()
        try:
            while True:
                item = event_queue.get()
                if item is _SENTINEL:
                    return
                yield item  # type: ignore[misc]
        finally:
            thread.join()

    def _run_in_thread(
        self,
        system_prompt: str,
        history: Sequence[ConversationTurn],
        message: str,
        tool_context: ChatToolContext,
        max_tool_iterations: int,
        event_queue: queue.Queue[ChatStreamEvent | object],
    ) -> None:
        try:
            asyncio.run(
                self._produce(
                    system_prompt, history, message, tool_context, max_tool_iterations, event_queue
                )
            )
        finally:
            event_queue.put(_SENTINEL)

    async def _produce(
        self,
        system_prompt: str,
        history: Sequence[ConversationTurn],
        message: str,
        tool_context: ChatToolContext,
        max_tool_iterations: int,
        event_queue: queue.Queue[ChatStreamEvent | object],
    ) -> None:
        collected: list[ToolCallSummary] = []

        def _capture(
            tool_name: str, sql_text: str | None, outcome: SqlToolOutcome, latency_ms: int
        ) -> None:
            tool_context.on_tool_call(tool_name, sql_text, outcome, latency_ms)
            summary = _summarize(tool_name, outcome)
            collected.append(ToolCallSummary(tool_name=tool_name, summary=summary))

        wrapped_context = dataclasses.replace(tool_context, on_tool_call=_capture)

        agent: Agent[ChatToolContext] = Agent(
            name="trueup-chat-assistant",
            instructions=system_prompt,
            model=self._model,
            tools=[_get_database_schema_tool, _execute_read_only_sql_tool],
        )
        input_items: list[dict[str, Any]] = [
            {"role": turn.role, "content": turn.content} for turn in history
        ]
        input_items.append({"role": "user", "content": message})

        try:
            # `input_items` is a plain list of {"role", "content"} dicts -- a valid input shape
            # at runtime, but the SDK's stubs type this parameter as a large TypedDict union
            # mypy cannot structurally match against `list[dict[str, Any]]`.
            result = Runner.run_streamed(
                agent,
                input_items,  # type: ignore[arg-type]
                context=wrapped_context,
                max_turns=max_tool_iterations,
            )
            async for event in result.stream_events():
                if isinstance(event, RawResponsesStreamEvent):
                    data = event.data
                    if getattr(data, "type", "") == "response.output_text.delta":
                        delta = getattr(data, "delta", "")
                        if delta:
                            event_queue.put(ChatTokenEvent(text=delta))

            final_output = result.final_output
            final_text = final_output if isinstance(final_output, str) else str(final_output)
            event_queue.put(ChatCompletedEvent(final_text=final_text, tool_calls=tuple(collected)))
        except Exception as exc:
            # Never a raw provider error to the customer (S11 §5.3, OWASP A05) -- logged in full
            # server-side; this event is the only thing that reaches the client.
            log.error("chat_agent_turn_failed", exc_info=exc)
            event_queue.put(
                ChatErrorEvent(message="the assistant is temporarily unavailable; please try again")
            )


__all__ = ["OpenAIAgentAdapter"]
