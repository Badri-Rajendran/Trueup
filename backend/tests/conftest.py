"""Shared test fixtures.

**Real PostgreSQL, never SQLite** (S0 §11). This design's correctness depends on CHECK constraint
semantics, revoked UPDATE/DELETE grants, Row-Level Security, NUMERIC precision, FOR UPDATE SKIP
LOCKED and advisory locks — none of which SQLite has. A suite that passed against SQLite would
leave every one of those invariants unverified, which is worse than no coverage because it looks
like coverage.

Start the database with `docker compose up -d` from the repository root. Defaults below match
`docker-compose.yml`, so `uv run pytest` works with no `.env` present.

Two session fixtures, for a reason that is easy to get wrong:

- `db_session` wraps each test in a transaction rolled back on teardown. Fast, and the right
  default.
- `db_committing` really commits, truncating afterwards. Required by any test whose subject only
  happens *at* COMMIT — most importantly S1's `DEFERRABLE INITIALLY DEFERRED` ledger-balance
  trigger. Under `db_session` that trigger never fires at all, so a test asserting it rejects an
  unbalanced entry would pass while proving nothing.

Engines are exposed per role because RLS does not apply to a table's owner: an isolation test
connected as `trueup_owner` would pass regardless of whether any policy exists.
"""

from __future__ import annotations

import base64
import os
from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session

from app import create_app
from app.config import Settings
from app.core.crypto import reset_cipher
from app.extensions import dispose_engines

TEST_DB_HOST = os.environ.get("TEST_DB_HOST", "localhost")
TEST_DB_PORT = os.environ.get("TEST_DB_PORT", "5433")
TEST_DB_NAME = os.environ.get("TEST_DB_NAME", "trueup_test")
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6380/1")


def _dsn(role: str) -> str:
    return (
        f"postgresql+psycopg://trueup_{role}:trueup_{role}"
        f"@{TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}"
    )


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Settings pointed at the test database, independent of any .env on the machine."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        SECRET_KEY="test-secret-key-not-used-anywhere-else",
        DATABASE_URL=_dsn("app"),
        DATABASE_URL_WORKER=_dsn("worker"),
        DATABASE_URL_OWNER=_dsn("owner"),
        DATABASE_URL_CHAT=_dsn("chat_readonly"),
        REDIS_URL=TEST_REDIS_URL,
        FLASK_ENV="testing",
        LOCAL_CIPHER_KEY=base64.b64encode(b"0" * 32).decode(),
        FEE_RATE_PCT="0.0",
    )


@pytest.fixture(scope="session")
def owner_engine(test_settings: Settings) -> Iterator[Engine]:
    """Schema owner. Creates and drops schema; RLS does not constrain it."""
    engine = create_engine(test_settings.sqlalchemy_url_owner, future=True)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - environment problem, not a test failure
        pytest.exit(
            f"Cannot reach the test database at {TEST_DB_HOST}:{TEST_DB_PORT}/{TEST_DB_NAME}. "
            f"Run `docker compose up -d` from the repository root. ({exc})",
            returncode=1,
        )
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(test_settings: Settings) -> Iterator[Engine]:
    """The web API's role. No BYPASSRLS — use this for every tenant-isolation assertion."""
    engine = create_engine(test_settings.sqlalchemy_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def worker_engine(test_settings: Settings) -> Iterator[Engine]:
    """Jobs and outbox worker. BYPASSRLS, by design."""
    engine = create_engine(test_settings.sqlalchemy_url_worker, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def chat_engine(test_settings: Settings) -> Iterator[Engine]:
    """S11's `chat_readonly` role (ADR 19). Granted `SELECT` on the curated chat views only — use
    this for every assertion that the chat tool cannot reach beyond them."""
    engine = create_engine(test_settings.sqlalchemy_url_chat, future=True)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(owner_engine: Engine) -> Iterator[Session]:
    """Transaction-per-test, rolled back on teardown. The default.

    Note the limitation in this module's docstring: deferred constraint triggers never fire here,
    because nothing ever commits. Use `db_committing` when COMMIT itself is the subject.
    """
    connection = owner_engine.connect()
    transaction = connection.begin()
    session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def db_committing(owner_engine: Engine) -> Iterator[Session]:
    """A session that really commits, with every table truncated afterwards.

    Required by tests whose subject is COMMIT-time behaviour: the ledger-balance deferred trigger
    (S1 §6, ADR 17), revoked UPDATE/DELETE grants, and advisory-lock contention.
    """
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        _truncate_all(owner_engine)


def _truncate_all(engine: Engine) -> None:
    with engine.begin() as connection:
        tables = connection.execute(
            text(
                "SELECT tablename FROM pg_tables "
                "WHERE schemaname = 'public' AND tablename <> 'alembic_version'"
            )
        ).scalars().all()
        if tables:
            joined = ", ".join(f'public."{name}"' for name in tables)
            connection.execute(text(f"TRUNCATE {joined} RESTART IDENTITY CASCADE"))


@pytest.fixture
def app(test_settings: Settings) -> Iterator[Flask]:
    flask_app = create_app(test_settings)
    flask_app.config.update(TESTING=True)
    yield flask_app
    dispose_engines()
    reset_cipher()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()
