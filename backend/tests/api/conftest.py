from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, text

from app.models.identity.customer import Customer
from app.models.identity.staff import Staff


@pytest.fixture
def api_app(app: Flask) -> Flask:
    """`create_app()` already wires auth (blueprint + sessions/CSRF/login-manager); this fixture
    is kept as the `tests/api/` entry point so a test only has to depend on one fixture name."""
    return app


@pytest.fixture
def api_client(api_app: Flask) -> FlaskClient:
    return api_app.test_client()


@pytest.fixture(autouse=True)
def _reset_rate_limits(api_app: Flask) -> None:
    """Flask-Limiter's storage is Redis (S0 §7.4) and outlives any one test — without a reset, an
    earlier test's login attempts count toward a later test's throttling assertions."""
    from app.extensions import limiter

    with api_app.app_context():
        limiter.reset()


@pytest.fixture(scope="session", autouse=True)
def _identity_tables(owner_engine: Engine) -> Iterator[None]:
    """`customer`/`staff` on demand, the same way every other DB-touching test in this repo
    creates its own tables (`tests/integration/test_ops_spine.py`'s `ops_tables` fixture) — nothing
    in this project runs Alembic against the test database, so a fixture that assumed the tables
    already existed left the whole `tests/api/` package unable to run at all.
    """
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    Staff.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    Customer.__table__.drop(bind=owner_engine, checkfirst=True)
    Staff.__table__.drop(bind=owner_engine, checkfirst=True)


@pytest.fixture(autouse=True)
def _clean_identity_tables(owner_engine: Engine, _identity_tables: None) -> Iterator[None]:
    """Controllers under test open their own real `UnitOfWork` and commit for real (unlike
    `db_session`'s per-test rollback) — this truncates what they wrote so one test's registered
    customer/staff rows can never leak into the next."""
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text("TRUNCATE customer, staff RESTART IDENTITY CASCADE"))

