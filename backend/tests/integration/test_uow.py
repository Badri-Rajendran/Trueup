"""`UnitOfWork`'s transaction boundary against real Postgres, including `SET LOCAL`-style
transaction-scoping SQLite has no equivalent of (S0 §5, ADR 14)."""

from __future__ import annotations

import uuid
from functools import cached_property
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.uow import SessionRole, UnitOfWork
from app.extensions import DbRole, dispose_engines, init_engines

if TYPE_CHECKING:
    from app.config import Settings


@pytest.fixture
def engines(test_settings: Settings) -> None:
    """Populates the engine registry so the default (non-injected) session_factory path runs too."""
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def probe_table(db_committing: Session):
    """Throwaway table for the life of one test; never a real model."""
    db_committing.execute(text("CREATE TABLE uow_probe (id serial primary key, note text)"))
    db_committing.commit()
    yield "uow_probe"
    db_committing.execute(text("DROP TABLE IF EXISTS uow_probe"))
    db_committing.commit()


def _current_setting(session: Session, name: str) -> str | None:
    return session.execute(text("SELECT current_setting(:name, true)"), {"name": name}).scalar_one()


# --- tenant context: set_config('app.role'/'app.customer_id', ..., true) -----------------------


def test_customer_session_sets_role_and_customer_id_gucs(owner_engine: Engine) -> None:
    customer_id = uuid.uuid4()
    connection = owner_engine.connect()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        with UnitOfWork(
            customer_id=customer_id,
            role=SessionRole.CUSTOMER,
            session_factory=lambda: session,
        ) as uow:
            assert _current_setting(uow.session, "app.role") == "customer"
            assert _current_setting(uow.session, "app.customer_id") == str(customer_id)
            uow.commit()
    finally:
        session.close()
        connection.close()


def test_adviser_session_does_not_require_a_customer_id(owner_engine: Engine) -> None:
    connection = owner_engine.connect()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        with UnitOfWork(
            customer_id=None,
            role=SessionRole.ADVISER,
            session_factory=lambda: session,
        ) as uow:
            assert _current_setting(uow.session, "app.role") == "adviser"
            assert _current_setting(uow.session, "app.customer_id") == ""
            uow.commit()
    finally:
        session.close()
        connection.close()


def test_customer_role_without_a_customer_id_is_rejected_immediately() -> None:
    """Fails at construction, not query time, mirroring ADR 6's `as_of` discipline."""
    with pytest.raises(ValueError, match="customer_id"):
        UnitOfWork(customer_id=None, role=SessionRole.CUSTOMER)


def test_set_local_scope_does_not_survive_the_transaction(owner_engine: Engine) -> None:
    """`set_config(..., true)` behaves like `SET LOCAL`: gone once its transaction ends."""
    customer_id = uuid.uuid4()
    connection = owner_engine.connect()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        with UnitOfWork(
            customer_id=customer_id,
            role=SessionRole.CUSTOMER,
            session_factory=lambda: session,
        ) as uow:
            assert _current_setting(uow.session, "app.customer_id") == str(customer_id)
            uow.commit()

        # Reusing the same connection proves the GUC reset at COMMIT, not a new-connection artifact.
        leaked = _current_setting(session, "app.customer_id")
        assert leaked in ("", None)
        session.rollback()
    finally:
        session.close()
        connection.close()


# --- commit / rollback discipline ---------------------------------------------------------------

_INSERT_PROBE = text("INSERT INTO uow_probe (note) VALUES (:note)")
_COUNT_PROBE = text("SELECT count(*) FROM uow_probe")


def test_exiting_without_commit_rolls_back(
    probe_table: str, db_committing: Session, engines: None
) -> None:
    assert probe_table == "uow_probe"
    with UnitOfWork(
        customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER
    ) as uow:
        uow.session.execute(_INSERT_PROBE, {"note": "never persisted"})
        # No commit() call.

    count = db_committing.execute(_COUNT_PROBE).scalar_one()
    assert count == 0


def test_explicit_commit_persists_the_write(
    probe_table: str, db_committing: Session, engines: None
) -> None:
    assert probe_table == "uow_probe"
    with UnitOfWork(
        customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER
    ) as uow:
        uow.session.execute(_INSERT_PROBE, {"note": "persisted"})
        uow.commit()

    count = db_committing.execute(_COUNT_PROBE).scalar_one()
    assert count == 1


def test_explicit_rollback_discards_the_write(
    probe_table: str, db_committing: Session, engines: None
) -> None:
    assert probe_table == "uow_probe"
    with UnitOfWork(
        customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER
    ) as uow:
        uow.session.execute(_INSERT_PROBE, {"note": "rolled back"})
        uow.rollback()

    count = db_committing.execute(_COUNT_PROBE).scalar_one()
    assert count == 0


class _BoomError(Exception):
    """Stands in for an arbitrary service failure."""


def test_exception_inside_the_block_rolls_back_and_propagates(
    probe_table: str, db_committing: Session, engines: None
) -> None:
    assert probe_table == "uow_probe"
    with pytest.raises(_BoomError), UnitOfWork(
        customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER
    ) as uow:
        uow.session.execute(_INSERT_PROBE, {"note": "boom"})
        raise _BoomError("service-level failure")

    count = db_committing.execute(_COUNT_PROBE).scalar_one()
    assert count == 0


# --- misuse guards --------------------------------------------------------------------------------


def test_session_property_raises_before_enter() -> None:
    uow = UnitOfWork(customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER)
    with pytest.raises(RuntimeError, match="outside an active"):
        _ = uow.session


def test_reentry_is_rejected(engines: None) -> None:
    uow = UnitOfWork(customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER)
    with uow:
        uow.commit()
    with pytest.raises(RuntimeError, match="not reentrant"), uow:
        pass


def test_default_db_role_is_app() -> None:
    uow = UnitOfWork(customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER)
    assert uow.db_role is DbRole.APP


# --- the extension mechanism: subclass + cached_property ------------------------------------------


class _ProbeUnitOfWork(UnitOfWork):
    """Stands in for a wave-owned `LedgerUnitOfWork`/`OrdersUnitOfWork`."""

    @cached_property
    def probe(self) -> object:
        return object()


def test_subclass_can_add_a_cached_repository_accessor(engines: None) -> None:
    with _ProbeUnitOfWork(
        customer_id=uuid.uuid4(), role=SessionRole.CUSTOMER, db_role=DbRole.OWNER
    ) as uow:
        first = uow.probe
        second = uow.probe
        assert first is second  # cached, not rebuilt per access
        uow.commit()
