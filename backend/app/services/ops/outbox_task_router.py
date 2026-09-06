"""Fans a claimed `job_outbox` row out to the handler for its `task`, matching `OutboxTaskHandler`'s
shape (`app/workers/outbox.py`)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class UnregisteredOutboxTaskError(RuntimeError):
    """Raised when a claimed row's task has no route -- a wiring gap, not a no-op."""


class OutboxTaskRouter:
    def __init__(self, *, routes: Mapping[str, Callable[[dict[str, Any]], None]]) -> None:
        self._routes = dict(routes)

    def handle(self, *, task: str, payload: dict[str, Any]) -> None:
        """Matches `OutboxTaskHandler`'s shape (`app/workers/outbox.py`)."""
        route = self._routes.get(task)
        if route is None:
            raise UnregisteredOutboxTaskError(f"no outbox route for task {task!r}")
        route(payload)


__all__ = ["OutboxTaskRouter", "UnregisteredOutboxTaskError"]
