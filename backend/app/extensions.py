"""Shared extension and engine instances, initialised by `app/__init__.py`'s factory.

Four DB engines (one per `DbRole`) enforce the RLS/credential boundary from S0 §7.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.db import DbRole, reset_session_factory_resolver, set_session_factory_resolver

if TYPE_CHECKING:
    from app.config import Settings

__all__ = [
    "DbRole",
    "dispose_engines",
    "get_engine",
    "get_session_factory",
    "init_engines",
    "limiter",
    "make_redis",
    "talisman",
]


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
        DbRole.CHAT: settings.sqlalchemy_url_chat,
    }
    for role, url in urls.items():
        engine = create_engine(
            url,
            pool_pre_ping=True,
            # NUMERIC must arrive as Decimal, never float (S0 §10.9).
            echo=False,
            future=True,
        )
        _engines[role] = engine
        _session_factories[role] = sessionmaker(bind=engine, expire_on_commit=False)
    set_session_factory_resolver(get_session_factory)


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
    reset_session_factory_resolver()


def make_redis(settings: Settings) -> redis.Redis:
    """Sessions and rate-limit counters only. Never financial state (ADR 13, S0 §9)."""
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
