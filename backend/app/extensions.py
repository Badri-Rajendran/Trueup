"""Shared extension and engine instances.

Declared here, initialised in `app/__init__.py`'s factory — never constructed inline in a
controller or service (`backend/CLAUDE.md`).

Three database engines, not one, because S0 §7.3 makes the RLS bypass a credential boundary:
the web API's engine uses a role without `BYPASSRLS` and is structurally incapable of reading
across tenants, whatever a future request-handling bug does. Jobs and the outbox worker use the
`worker` engine; migrations use `owner`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

import redis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

if TYPE_CHECKING:
    from app.config import Settings


class DbRole(StrEnum):
    """Which database credential a connection uses. Not interchangeable — see module docstring."""

    APP = "app"
    """The web API. No BYPASSRLS. Every request-scoped UnitOfWork uses this."""

    WORKER = "worker"
    """Scheduled jobs and the outbox worker, which legitimately span every customer."""

    OWNER = "owner"
    """Schema owner. Migrations only; never serves a request."""


_engines: dict[DbRole, Engine] = {}
_session_factories: dict[DbRole, sessionmaker[Session]] = {}

limiter = Limiter(key_func=get_remote_address)
talisman = Talisman()


def init_engines(settings: Settings) -> None:
    """Build one engine per role. Idempotent, so repeated app factory calls in tests are safe."""
    dispose_engines()
    urls = {
        DbRole.APP: settings.sqlalchemy_url,
        DbRole.WORKER: settings.sqlalchemy_url_worker,
        DbRole.OWNER: settings.sqlalchemy_url_owner,
    }
    for role, url in urls.items():
        engine = create_engine(
            url,
            pool_pre_ping=True,
            # NUMERIC must arrive as Decimal, never float — a float in a money path is a bug
            # (S0 §10.9). psycopg3 already does this; stated so a future driver swap cannot
            # silently change it.
            echo=False,
            future=True,
        )
        _engines[role] = engine
        _session_factories[role] = sessionmaker(bind=engine, expire_on_commit=False)


def get_engine(role: DbRole = DbRole.APP) -> Engine:
    if role not in _engines:
        raise RuntimeError(
            f"No engine for role {role!r}. Call init_engines() during application startup."
        )
    return _engines[role]


def get_session_factory(role: DbRole = DbRole.APP) -> sessionmaker[Session]:
    if role not in _session_factories:
        raise RuntimeError(
            f"No session factory for role {role!r}. Call init_engines() during startup."
        )
    return _session_factories[role]


def dispose_engines() -> None:
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _session_factories.clear()


def make_redis(settings: Settings) -> redis.Redis:
    """Sessions and rate-limit counters only. Never financial state (ADR 13, S0 §9)."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
