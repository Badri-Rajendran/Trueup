"""Row-Level Security on `customer`: a customer session can't read another customer's row even
with the app-layer guard bypassed, and adviser/admin sessions can read across customers under the
same policy (S0 §7.3, ADR 15, ADR 17)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text

from app.core.uow import SessionRole, UnitOfWork
from app.extensions import DbRole, dispose_engines, init_engines
from app.models.identity.customer import Customer

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

    from app.config import Settings


@pytest.fixture(autouse=True)
def engines(test_settings: Settings) -> None:
    """Populates the engine registry `UnitOfWork`'s default session_factory needs."""
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture(autouse=True)
def customer_table(owner_engine: Engine) -> Iterator[None]:
    """Table create/drop fires `Customer.__table__`'s own RLS-policy DDL events."""
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text(f'DROP TABLE IF EXISTS "{Customer.__table__.name}" CASCADE'))


def _insert_two_customers(db_committing: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Owner-role insert; pure setup, since RLS does not constrain the schema owner."""
    customer_a = Customer(email=f"a-{uuid.uuid4()}@trueup.test", password_hash="hash-a")
    customer_b = Customer(email=f"b-{uuid.uuid4()}@trueup.test", password_hash="hash-b")
    db_committing.add_all([customer_a, customer_b])
    db_committing.commit()
    return customer_a.id, customer_b.id


def test_customer_session_cannot_see_another_customers_row_even_without_the_app_guard(
    db_committing: Session,
) -> None:
    customer_a_id, customer_b_id = _insert_two_customers(db_committing)

    with UnitOfWork(
        customer_id=customer_a_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        # Raw query under the `app` credential, no repository filter -- read inside the block
        # since `UnitOfWork.__exit__` rolls back and detaches these ORM instances.
        visible_ids = {row.id for row in uow.session.execute(select(Customer)).scalars().all()}
    assert visible_ids == {customer_a_id}
    assert customer_b_id not in visible_ids


def test_adviser_session_can_read_across_customers_under_the_same_rls_policy(
    db_committing: Session,
) -> None:
    customer_a_id, customer_b_id = _insert_two_customers(db_committing)

    with UnitOfWork(customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP) as uow:
        visible_ids = {row.id for row in uow.session.execute(select(Customer)).scalars().all()}

    assert {customer_a_id, customer_b_id} <= visible_ids


def test_admin_session_can_also_read_across_customers(db_committing: Session) -> None:
    """Covers the `admin` branch separately so a bug scoped to one role literal doesn't slip by."""
    customer_a_id, customer_b_id = _insert_two_customers(db_committing)

    with UnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow:
        visible_ids = {row.id for row in uow.session.execute(select(Customer)).scalars().all()}

    assert {customer_a_id, customer_b_id} <= visible_ids
