"""Postgres LISTEN/NOTIFY outbox consumer.

The listening connection is deliberately a standalone psycopg connection, outside SQLAlchemy's
pool. It stays in autocommit mode so LISTEN registration and notification delivery are not tied to
the short UnitOfWork transactions used to claim and complete work.
"""

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
    # A `@property` here, not a bare attribute annotation: every real UnitOfWork exposes its
    # repositories as `@cached_property`, and a Protocol's bare-attribute form expects a settable
    # instance attribute, which a read-only property/cached_property does not structurally satisfy
    # under strict mypy (the same fix `event_intake.py`'s equivalent Protocol already applies).
    @property
    def outbox(self) -> OutboxRepository: ...

    def __enter__(self) -> Self: ...

    # The real 3-argument context-manager `__exit__` (matching `app.core.uow.UnitOfWork`'s own
    # signature exactly, the same proven pattern `event_intake.py`'s equivalent Protocol uses) --
    # a looser `*args: object` here structurally rejects any real `UnitOfWork` subclass under
    # strict Protocol matching, since a subclass's narrower, concretely-typed `__exit__` cannot
    # satisfy a Protocol that promises callers may pass arbitrary positional `object`s.
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
        """Process one row, returning whether work was found.

        Claiming commits before handler execution. Consequently, slow provider I/O never holds the
        row lock or database transaction open, and another worker cannot claim the same row.
        """
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
