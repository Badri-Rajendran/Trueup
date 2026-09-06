"""`OutboxTaskRouter` -- the composition point that fans a claimed `job_outbox` row out to the
handler for its `task`, matching `OutboxTaskHandler`'s shape (`app/workers/outbox.py`) so an
`OutboxWorker` can be constructed with exactly one handler regardless of how many task types this
codebase's services actually enqueue (`grep -rn "outbox.enqueue(" app/services/` currently finds
three: `submit_order_to_broker`, `charge_fee`, `process_inbound_event`).

Deliberately separate from the CLI wiring that constructs its routes (`app/jobs/__init__.py`'s
`outbox-worker` command): that wiring needs real database/broker/payment credentials and cannot be
unit tested without them, the same way `daily_valuation_command`'s own credential gating is
untested inline CLI logic elsewhere in this file -- but *which task routes to which callable* is
ordinary, DB-free logic with no reason to share that untestability, so it lives here instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


class UnregisteredOutboxTaskError(RuntimeError):
    """Raised rather than silently dropping a claimed row whose task has no route -- an outbox
    row with no handler is a wiring gap, not a no-op (the same reasoning
    `InboundEventDispatcher.UnregisteredSourceError` already states for its own, narrower case)."""


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
