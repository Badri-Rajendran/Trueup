"""`OutboxTaskRouter` (`app/services/ops/outbox_task_router.py`) -- pure routing logic, no
database or provider needed, unlike the CLI wiring (`outbox-worker` in `app/jobs/__init__.py`)
that constructs its real routes with live credentials."""

from __future__ import annotations

import pytest

from app.services.ops.outbox_task_router import OutboxTaskRouter, UnregisteredOutboxTaskError


def test_routes_a_task_to_its_registered_callable() -> None:
    received: list[dict[str, object]] = []
    router = OutboxTaskRouter(routes={"submit_order_to_broker": received.append})

    router.handle(task="submit_order_to_broker", payload={"order_id": "abc"})

    assert received == [{"order_id": "abc"}]


def test_routes_each_task_only_to_its_own_callable() -> None:
    broker_calls: list[dict[str, object]] = []
    fee_calls: list[dict[str, object]] = []
    router = OutboxTaskRouter(
        routes={
            "submit_order_to_broker": broker_calls.append,
            "charge_fee": fee_calls.append,
        }
    )

    router.handle(task="charge_fee", payload={"fee_charge_id": "xyz"})

    assert fee_calls == [{"fee_charge_id": "xyz"}]
    assert broker_calls == []


def test_an_unregistered_task_raises_rather_than_silently_dropping_the_row() -> None:
    router = OutboxTaskRouter(routes={"charge_fee": lambda payload: None})

    with pytest.raises(UnregisteredOutboxTaskError, match="mystery_task"):
        router.handle(task="mystery_task", payload={})


def test_a_handler_raising_propagates_to_the_caller() -> None:
    """`OutboxWorker.drain_once` is what actually catches this (retry-then-dead-letter) --
    `OutboxTaskRouter` itself must not swallow it first."""

    def _boom(payload: dict[str, object]) -> None:
        raise RuntimeError("provider unavailable")

    router = OutboxTaskRouter(routes={"charge_fee": _boom})

    with pytest.raises(RuntimeError, match="provider unavailable"):
        router.handle(task="charge_fee", payload={})
