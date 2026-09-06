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
    """The `tests/api/` entry point fixture, so a test depends on one fixture name."""
    return app


@pytest.fixture
def api_client(api_app: Flask) -> FlaskClient:
    return api_app.test_client()


@pytest.fixture(autouse=True)
def _reset_rate_limits(api_app: Flask) -> None:
    """Flask-Limiter's Redis storage (S0 §7.4) outlives a test; reset so counts don't leak."""
    from app.extensions import limiter

    with api_app.app_context():
        limiter.reset()


@pytest.fixture(scope="session", autouse=True)
def _identity_tables(owner_engine: Engine) -> Iterator[None]:
    """Creates `customer`/`staff` on demand; nothing runs Alembic against the test database."""
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    Staff.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    Customer.__table__.drop(bind=owner_engine, checkfirst=True)
    Staff.__table__.drop(bind=owner_engine, checkfirst=True)


@pytest.fixture(autouse=True)
def _clean_identity_tables(owner_engine: Engine, _identity_tables: None) -> Iterator[None]:
    """Controllers commit for real; truncates so rows don't leak between tests."""
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text("TRUNCATE customer, staff RESTART IDENTITY CASCADE"))

