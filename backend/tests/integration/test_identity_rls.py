"""Row-Level Security on `customer` (S0 §7.3, ADR 15, ADR 17) — the two required tests, and only
both together are sufficient:

1. A `customer`-role session cannot read another customer's row, **even with the application-layer
   guard disabled** — proving the database is the real control, not `BaseRepository`'s filter.
2. An `adviser`-role session *can* read across customers under the same policy — proving the
   role-aware branch actually works, not just the restrictive one (the gap ADR 17 closed after the
   original single-customer-only policy would have silently blocked FR-31's own screen).

Both queries below go through the **`app` role's own credential** (`DbRole.APP`, no BYPASSRLS —
`app_engine`/`test_settings.sqlalchemy_url`) and bypass `SqlCustomerRepository` entirely, issuing a
raw `select(Customer)` directly against `uow.session` — this is "the application-layer guard
disabled" from S0 §7.3's required-test wording: nothing but Postgres itself is left to enforce
tenant isolation for this query.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select

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
    """`UnitOfWork`'s default session_factory path needs the engine registry populated."""
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture(autouse=True)
def customer_table(owner_engine: Engine) -> Iterator[None]:
    """Self-sufficient per-file table setup, matching `tests/integration/test_ops_spine.py`'s
    `ops_tables` fixture — this file's whole point is proving RLS actually filters, so the table
    must exist *with* its policy, not merely exist. `Customer.__table__`'s own `after_create`/
    `before_drop` DDL events (`app/models/identity/customer.py`) enable RLS and create/drop the
    `tenant_isolation` policy automatically; nothing here needs to duplicate that SQL.
    """
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    Customer.__table__.drop(bind=owner_engine, checkfirst=True)


def _insert_two_customers(db_committing: Session) -> tuple[uuid.UUID, uuid.UUID]:
    """Owner-role insert — RLS does not constrain the schema owner, so this is pure setup, not
    part of what either test below is proving."""
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
        # No SqlCustomerRepository, no _tenant_scoped() filter — a raw query under the `app`
        # credential. If RLS were not doing the filtering, this would return customer_b too.
        # `visible_ids` is read inside the block: `UnitOfWork.__exit__` rolls back (nothing was
        # committed) and closes the session, which expires and detaches these ORM instances.
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
    """`admin` is the other branch of `current_setting('app.role') IN ('adviser', 'admin')` —
    covered separately since a policy bug scoped to only one of the two role literals would
    otherwise pass the adviser test above."""
    customer_a_id, customer_b_id = _insert_two_customers(db_committing)

    with UnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow:
        visible_ids = {row.id for row in uow.session.execute(select(Customer)).scalars().all()}

    assert {customer_a_id, customer_b_id} <= visible_ids
