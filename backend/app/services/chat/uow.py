"""`ChatUnitOfWork` — S11's own aggregate (`chat_session`/`chat_message`/`chat_tool_call`), the
same thin composition shape `RestatementUnitOfWork` uses (S0 §5's documented extension mechanism).

Runs under `DbRole.APP` (the default), like every other customer-facing feature's `UnitOfWork` --
these three tables are ordinary application data the web API role already has full CRUD on. This
is entirely separate from `DbRole.CHAT`, which `ChatOrchestrationService` uses for a raw,
short-lived connection dedicated to running the LLM's *validated* SQL against the curated views
(ADR 19) -- that connection never goes through the ORM or this `UnitOfWork` at all.
"""

from __future__ import annotations

from app.models.chat import ChatModelsUnitOfWork


class ChatUnitOfWork(ChatModelsUnitOfWork):
    pass


__all__ = ["ChatUnitOfWork"]
