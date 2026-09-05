from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.ops.job_outbox import JobOutbox, JobOutboxStatus
from app.workers.outbox import OutboxWorker


class _Outbox:
    def __init__(self, row: JobOutbox | None) -> None:
        self.row = row
        self.completed: list[tuple[uuid.UUID, str]] = []
        self.retried: list[dict[str, Any]] = []

    def claim_next(self, *, worker_id: str, now: datetime) -> JobOutbox | None:
        if self.row is not None:
            self.row.status = JobOutboxStatus.PROCESSING
            self.row.locked_by = worker_id
            self.row.attempts += 1
        return self.row

    def complete(self, *, outbox_id: uuid.UUID, worker_id: str) -> None:
        self.completed.append((outbox_id, worker_id))

    def retry_or_dead_letter(self, **kwargs: Any) -> JobOutboxStatus:
        self.retried.append(kwargs)
        return JobOutboxStatus.PENDING


class _Uow:
    def __init__(self, outbox: _Outbox) -> None:
        self.outbox = outbox
        self.committed = False

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


class _Handler:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def handle(self, *, task: str, payload: dict[str, Any]) -> None:
        self.calls.append((task, payload))
        if self.failure is not None:
            raise self.failure


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def _row() -> JobOutbox:
    return JobOutbox(
        id=uuid.uuid4(), task="process_inbound_event", payload={"id": "event-1"}, attempts=0
    )


def test_claimed_work_is_committed_before_its_handler_runs() -> None:
    outbox = _Outbox(_row())
    claim_uow, completion_uow = _Uow(outbox), _Uow(outbox)
    handler = _Handler()
    worker = OutboxWorker(
        uow_factory=iter((claim_uow, completion_uow)).__next__,
        handler=handler,
        worker_id="worker-a",
        max_attempts=3,
        clock=lambda: NOW,
    )

    assert worker.drain_once() is True
    assert claim_uow.committed is True
    assert handler.calls == [("process_inbound_event", {"id": "event-1"})]
    assert completion_uow.committed is True
    assert outbox.completed == [(outbox.row.id, "worker-a")]  # type: ignore[union-attr]


def test_handler_failure_schedules_exponential_retry_after_claim_commit() -> None:
    outbox = _Outbox(_row())
    claim_uow, failure_uow = _Uow(outbox), _Uow(outbox)
    worker = OutboxWorker(
        uow_factory=iter((claim_uow, failure_uow)).__next__,
        handler=_Handler(RuntimeError("provider unavailable")),
        worker_id="worker-a",
        max_attempts=3,
        clock=lambda: NOW,
    )

    assert worker.drain_once() is True
    assert claim_uow.committed is True
    assert outbox.retried[0]["next_attempt_at"] == datetime(2026, 9, 5, 0, 0, 1, tzinfo=UTC)
    assert outbox.retried[0]["max_attempts"] == 3
    assert failure_uow.committed is True


def test_empty_outbox_does_not_open_a_completion_transaction() -> None:
    outbox = _Outbox(None)
    claim_uow = _Uow(outbox)
    worker = OutboxWorker(
        uow_factory=lambda: claim_uow,
        handler=_Handler(),
        worker_id="worker-a",
        max_attempts=3,
        clock=lambda: NOW,
    )

    assert worker.drain_once() is False
    assert claim_uow.committed is True
