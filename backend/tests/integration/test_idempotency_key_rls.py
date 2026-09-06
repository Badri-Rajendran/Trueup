"""Row-Level Security on `idempotency_key` (I9, S0 §7.3 audit finding) -- this table caches a
customer's own request/response bodies (financial PII: order/funding responses) and is
tenant-scoped by `customer_id`, but was the only such table in the schema with no RLS policy at
all. Matches `test_ledger_rls.py`'s own established pattern for `posting`, the identical shape of
problem (a denormalized, non-native `customer_id`).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.core.db import DbRole
from app.core.uow import SessionRole, UnitOfWork
from app.models.ops.idempotency_key import IdempotencyKey
from tests.integration.conftest import insert_customer

pytestmark = pytest.mark.usefixtures("ledger_tables")


@pytest.fixture(autouse=True)
def _idempotency_key_table(owner_engine: Engine) -> Iterator[None]:
    IdempotencyKey.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text('DROP TABLE IF EXISTS "idempotency_key" CASCADE'))


def _insert_key(session: Session, customer_id: uuid.UUID, *, key: str) -> None:
    session.add(
        IdempotencyKey(
            customer_id=customer_id,
            key=key,
            request_hash="hash",
            response_status=201,
            response_body={},
            created_at=datetime.now(UTC),
        )
    )


def test_customer_session_cannot_see_another_customers_idempotency_keys(
    owner_engine: Engine,
) -> None:
    owner_session = Session(bind=owner_engine)
    customer_a_id = insert_customer(owner_session)
    customer_b_id = insert_customer(owner_session)
    _insert_key(owner_session, customer_a_id, key="key-a")
    _insert_key(owner_session, customer_b_id, key="key-b")
    owner_session.commit()
    owner_session.close()

    with UnitOfWork(
        customer_id=customer_a_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        visible_customer_ids = {
            row.customer_id for row in uow.session.execute(select(IdempotencyKey)).scalars().all()
        }

    assert visible_customer_ids == {customer_a_id}
    assert customer_b_id not in visible_customer_ids


def test_adviser_session_can_read_idempotency_keys_across_customers(
    owner_engine: Engine,
) -> None:
    owner_session = Session(bind=owner_engine)
    customer_a_id = insert_customer(owner_session)
    customer_b_id = insert_customer(owner_session)
    _insert_key(owner_session, customer_a_id, key="key-a")
    _insert_key(owner_session, customer_b_id, key="key-b")
    owner_session.commit()
    owner_session.close()

    with UnitOfWork(customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP) as uow:
        visible_customer_ids = {
            row.customer_id for row in uow.session.execute(select(IdempotencyKey)).scalars().all()
        }

    assert visible_customer_ids == {customer_a_id, customer_b_id}
