"""`PublishedSnapshotRepository.list_for_customer` (S6 §8, S12 §8) — keyset-pagination stability
against real Postgres: paging with `limit=2` across 5 seeded snapshots survives a new snapshot
inserted mid-walk into an already-yielded page's position, with no repeated or skipped row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.core.db import DbRole
from app.core.money import Money
from app.core.pagination import decode_cursor, paginate
from app.core.uow import SessionRole
from app.models.identity.customer import Customer
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.services.restatement.uow import RestatementUnitOfWork
from tests.integration.conftest import insert_customer

_TABLES = [Customer.__table__, PublishedSnapshot.__table__]


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("_tables")


def _seed_snapshot(
    db_committing,
    *,
    customer_id: uuid.UUID,
    period_start: date,
    snapshot_id: uuid.UUID | None = None,
) -> PublishedSnapshot:
    period_end = period_start + timedelta(days=27)
    snapshot = PublishedSnapshot(
        id=snapshot_id if snapshot_id is not None else uuid.uuid4(),
        customer_id=customer_id,
        period_start=period_start,
        period_end=period_end,
        publish_watermark=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC),
        twr=Decimal("0.0100000000"),
        balance=Money("1000.00"),
        holdings_json={},
        published_at=datetime.combine(period_end, datetime.min.time(), tzinfo=UTC),
    )
    db_committing.add(snapshot)
    db_committing.commit()
    return snapshot


def _cursor_key(snapshot: PublishedSnapshot) -> tuple[str, str, str]:
    return (
        snapshot.period_start.isoformat(),
        snapshot.publish_watermark.isoformat(),
        str(snapshot.id),
    )


def _decode_after(raw_cursor: str) -> tuple[date, datetime, uuid.UUID]:
    decoded = decode_cursor(raw_cursor)
    return (
        date.fromisoformat(decoded[0]),  # type: ignore[arg-type]
        datetime.fromisoformat(decoded[1]),  # type: ignore[arg-type]
        uuid.UUID(decoded[2]),  # type: ignore[arg-type]
    )


def test_list_for_customer_pagination_is_stable_under_a_mid_walk_insert(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    base = date(2026, 1, 1)
    # DESC order: seeded[4] (latest period_start) is newest ... seeded[0] is oldest.
    seeded = [
        _seed_snapshot(
            db_committing, customer_id=customer_id, period_start=base + timedelta(days=31 * i)
        )
        for i in range(5)
    ]
    newest_first = list(reversed(seeded))

    def _uow() -> RestatementUnitOfWork:
        return RestatementUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        )

    # `.items` are attached to each `with` block's own session; ids are extracted before it
    # closes (closing expires -- and detaches access to -- the loaded ORM instances).
    with _uow() as uow:
        rows = uow.published_snapshots.list_for_customer(customer_id, limit=2)
        page1 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page1_ids = [s.id for s in page1.items]
    assert page1_ids == [newest_first[0].id, newest_first[1].id]
    assert page1.next_cursor is not None

    # A snapshot tied on `period_start` with newest_first[1], given a deliberately-maximal `id`
    # (guaranteed greater than any uuid4) so the DESC tiebreak places it strictly before
    # newest_first[1] -- into page 1's already-yielded position -- after page 1 has already been
    # fetched.
    mid_insert = _seed_snapshot(
        db_committing,
        customer_id=customer_id,
        period_start=newest_first[1].period_start,
        snapshot_id=uuid.UUID(int=2**128 - 1),
    )

    after = _decode_after(page1.next_cursor)
    with _uow() as uow:
        rows = uow.published_snapshots.list_for_customer(customer_id, limit=2, after=after)
        page2 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page2_ids = [s.id for s in page2.items]
    assert page2_ids == [newest_first[2].id, newest_first[3].id]
    assert page2.next_cursor is not None

    after = _decode_after(page2.next_cursor)
    with _uow() as uow:
        rows = uow.published_snapshots.list_for_customer(customer_id, limit=2, after=after)
        page3 = paginate(rows, limit=2, cursor_key=_cursor_key)
        page3_ids = [s.id for s in page3.items]
    assert page3_ids == [newest_first[4].id]
    assert page3.next_cursor is None

    walked_ids = [*page1_ids, *page2_ids, *page3_ids]
    assert walked_ids == [s.id for s in newest_first]  # every seeded row exactly once, in order
    assert mid_insert.id not in walked_ids  # the mid-walk insert never leaks into the walk
