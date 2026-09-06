"""Postgres LISTEN/NOTIFY outbox consumer. The listening connection is a standalone, autocommit
psycopg connection outside SQLAlchemy's pool."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Protocol, Self

import psycopg
from sqlalchemy.engine import make_url

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Iterator
    from types import TracebackType

    from app.models.ops.job_outbox import JobOutbox, JobOutboxStatus


class OutboxRepository(Protocol):
    def claim_next(self, *, worker_id: str, now: datetime) -> JobOutbox | None: ...

    def complete(self, *, outbox_id: uuid.UUID, worker_id: str) -> None: ...

    def retry_or_dead_letter(
        self,
        *,
        outbox_id: uuid.UUID,
        worker_id: str,
        next_attempt_at: datetime,
        max_attempts: int,
    ) -> JobOutboxStatus: ...


class OutboxUnitOfWork(Protocol):
    # @property, not a bare attribute: real UnitOfWork exposes repos as @cached_property.
    @property
    def outbox(self) -> OutboxRepository: ...

    def __enter__(self) -> Self: ...

    # Matches UnitOfWork's concrete 3-arg __exit__ signature for strict Protocol matching.
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...

    def commit(self) -> None: ...


class OutboxTaskHandler(Protocol):
    """A task dispatcher. Handlers run after the claim transaction commits."""

    def handle(self, *, task: str, payload: dict[str, Any]) -> None: ...


class ListenConnection(Protocol):
    def execute(self, query: str) -> object: ...

    def notifies(self, *, timeout: float | None = None) -> Iterator[object]: ...


class OutboxWorker:
    """Claims durable work, invokes its handler outside a transaction, then records the outcome."""

    def __init__(
        self,
        *,
        uow_factory: Callable[[], OutboxUnitOfWork],
        handler: OutboxTaskHandler,
        worker_id: str,
        max_attempts: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        self._uow_factory = uow_factory
        self._handler = handler
        self._worker_id = worker_id
        self._max_attempts = max_attempts
        self._clock = clock

    def drain_once(self) -> bool:
        """Process one row, returning whether work was found. Claiming commits before handler
        execution, so slow provider I/O never holds the row lock open."""
        with self._uow_factory() as uow:
            row = uow.outbox.claim_next(worker_id=self._worker_id, now=self._clock())
            uow.commit()
        if row is None:
            return False

        try:
            self._handler.handle(task=row.task, payload=row.payload)
        except Exception:
            delay_seconds = 2 ** (row.attempts - 1)
            with self._uow_factory() as uow:
                uow.outbox.retry_or_dead_letter(
                    outbox_id=row.id,
                    worker_id=self._worker_id,
                    next_attempt_at=self._clock() + timedelta(seconds=delay_seconds),
                    max_attempts=self._max_attempts,
                )
                uow.commit()
            return True

        with self._uow_factory() as uow:
            uow.outbox.complete(outbox_id=row.id, worker_id=self._worker_id)
            uow.commit()
        return True

    def drain_ready(self) -> int:
        """Drain all currently claimable rows after a notification or startup sweep."""
        count = 0
        while self.drain_once():
            count += 1
        return count

    def listen_forever(self, connection: ListenConnection, *, timeout: float = 30.0) -> None:
        """Block for outbox notifications, with a sweep on each timeout for recovery."""
        connection.execute("LISTEN job_outbox_ready")
        while True:
            for _notification in connection.notifies(timeout=timeout):
                self.drain_ready()
            self.drain_ready()


def create_listen_connection(database_url: str) -> psycopg.Connection[Any]:
    """Open the worker's dedicated, autocommit psycopg connection for LISTEN/NOTIFY."""
    url = make_url(database_url)
    conninfo = url.set(drivername="postgresql").render_as_string(hide_password=False)
    return psycopg.connect(conninfo, autocommit=True)
