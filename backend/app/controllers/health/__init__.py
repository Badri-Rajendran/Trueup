"""Liveness and readiness probes (S0 §8): unauthenticated, and carrying no business data."""

from __future__ import annotations

from typing import Any

from flask import Blueprint
from sqlalchemy import text

from app.core.logging import get_logger
from app.extensions import DbRole, get_engine

health_bp = Blueprint("health", __name__, url_prefix="/health")

log = get_logger(__name__)


@health_bp.get("/live")
def live() -> dict[str, str]:
    """Is this process running? Touches nothing external."""
    return {"status": "alive"}


@health_bp.get("/ready")
def ready() -> tuple[dict[str, Any], int]:
    """Can this process serve traffic? Reports each dependency as a plain boolean, no internals."""
    checks = {"database": _database_reachable(), "redis": _redis_reachable()}
    ok = all(checks.values())
    return {"status": "ready" if ok else "not_ready", "checks": checks}, 200 if ok else 503


def _database_reachable() -> bool:
    try:
        with get_engine(DbRole.APP).connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        log.warning("readiness_check_failed", dependency="database", exc_info=True)
        return False
    return True


def _redis_reachable() -> bool:
    from flask import current_app

    try:
        client = current_app.extensions["trueup_redis"]
        client.ping()
    except Exception:
        log.warning("readiness_check_failed", dependency="redis", exc_info=True)
        return False
    return True
