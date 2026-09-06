"""PostgreSQL-only invariants for the operational intake and job spine."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.extensions import dispose_engines, init_engines
from app.models.ops import OpsUnitOfWork
from app.models.ops.inbound_event import (
    DuplicateInboundEventError,
    InboundEvent,
    InboundEventSource,
)
from app.models.ops.job_outbox import JobOutbox, JobOutboxRepository
from app.models.ops.job_run import JobCadence, JobRun
from app.workers.outbox import create_listen_connection

if TYPE_CHECKING:
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from app.config import Settings


@pytest.fixture(autouse=True)
def engines(test_settings: Settings) -> None:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def ops_tables(owner_engine: Engine):
    tables = [
        InboundEvent.__table__,
        JobOutbox.__table__,
        JobRun.__table__,
    ]
    # Per-table create/drop, not `create_all(tables=[...])`: the latter dispatches enum DDL
    # events for the whole shared metadata regardless of the `tables=` filter.
    for table in tables:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(tables):
        table.drop(bind=owner_engine, checkfirst=True)


def _worker_uow() -> OpsUnitOfWork:
    return OpsUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def test_inbound_event_unique_key_is_the_deduplication_mechanism(ops_tables: None) -> None:
    first = InboundEvent(
        source=InboundEventSource.ALPACA,
        source_event_id="fill-123",
        payload={"fill_id": "fill-123"},
        signature_verified=True,
    )
    duplicate = InboundEvent(
        source=InboundEventSource.ALPACA,
        source_event_id="fill-123",
        payload={"fill_id": "fill-123"},
        signature_verified=True,
    )

    with _worker_uow() as uow:
        uow.inbound_events.record(first)
        uow.commit()

    with _worker_uow() as uow:
        with pytest.raises(DuplicateInboundEventError):
            uow.inbound_events.record(duplicate)
        uow.commit()


def test_skip_locked_prevents_a_second_worker_from_claiming_the_same_row(ops_tables: None) -> None:
    with _worker_uow() as uow:
        uow.outbox.enqueue("process_inbound_event", {"inbound_event_id": str(uuid.uuid4())})
        uow.commit()

    # next_attempt_at server-defaults to real now(); a hardcoded "now" would fail claim_next.
    now = datetime.now(UTC)
    with _worker_uow() as first_uow:
        first = JobOutboxRepository(first_uow).claim_next(worker_id="first", now=now)
        assert first is not None
        with _worker_uow() as second_uow:
            second = JobOutboxRepository(second_uow).claim_next(worker_id="second", now=now)
            assert second is None
            second_uow.commit()
        first_uow.commit()


def test_postgres_notification_is_received_by_the_dedicated_listen_connection(
    ops_tables: None, test_settings: Settings
) -> None:
    with create_listen_connection(test_settings.sqlalchemy_url_worker) as listener:
        listener.execute("LISTEN job_outbox_ready")
        with _worker_uow() as uow:
            uow.notify_outbox_ready()
            uow.commit()
        notification = next(listener.notifies(timeout=1.0))
        assert notification.channel == "job_outbox_ready"


def test_monthly_job_run_index_allows_only_one_execution_per_month(
    ops_tables: None, db_committing: Session
) -> None:
    db_committing.add(
        JobRun(job_name="rebalance", cadence=JobCadence.MONTHLY, market_date=date(2026, 9, 1))
    )
    db_committing.commit()
    db_committing.add(
        JobRun(job_name="rebalance", cadence=JobCadence.MONTHLY, market_date=date(2026, 9, 30))
    )
    with pytest.raises(IntegrityError):
        db_committing.commit()
