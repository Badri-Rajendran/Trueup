"""Structured logging and correlation-ID plumbing, against real structlog/contextvars behavior
(S0 §7.4, OWASP A09)."""

from __future__ import annotations

import contextvars
import uuid

import structlog

from app.core.logging import (
    _add_correlation_id,
    configure_logging,
    get_correlation_id,
    get_logger,
    new_correlation_id,
    set_correlation_id,
)

# ---------------------------------------------------------------------------
# new_correlation_id
# ---------------------------------------------------------------------------


def test_new_correlation_id_returns_valid_uuid_string() -> None:
    cid = new_correlation_id()
    assert isinstance(cid, str)
    parsed = uuid.UUID(cid)  # must parse without raising
    assert str(parsed) == cid


def test_new_correlation_id_returns_unique_values() -> None:
    assert new_correlation_id() != new_correlation_id()


# ---------------------------------------------------------------------------
# set_correlation_id / get_correlation_id  (ContextVar round-trip)
# ---------------------------------------------------------------------------


def test_set_and_get_round_trip() -> None:
    cid = new_correlation_id()
    set_correlation_id(cid)
    assert get_correlation_id() == cid


def test_fresh_context_returns_none() -> None:
    """A context that never called `set_correlation_id` must read `None`, not crash."""
    ctx = contextvars.Context()  # truly empty, unlike copy_context()
    result = ctx.run(get_correlation_id)
    assert result is None


# ---------------------------------------------------------------------------
# _add_correlation_id processor
# ---------------------------------------------------------------------------


def test_add_correlation_id_injects_key_when_set() -> None:
    cid = new_correlation_id()
    set_correlation_id(cid)
    event_dict: structlog.types.EventDict = {"event": "test_event"}
    result = _add_correlation_id(None, "info", event_dict)
    assert result["correlation_id"] == cid


def test_add_correlation_id_omits_key_when_none() -> None:
    """No correlation ID set: the key must be absent, not present with a `None` value."""
    ctx = contextvars.Context()

    def _run() -> structlog.types.EventDict:
        event_dict: structlog.types.EventDict = {"event": "test_event"}
        return _add_correlation_id(None, "info", event_dict)

    result = ctx.run(_run)
    assert "correlation_id" not in result


# ---------------------------------------------------------------------------
# configure_logging — renderer selection
# ---------------------------------------------------------------------------


def test_configure_logging_json_selects_json_renderer() -> None:
    configure_logging(json_output=True)
    config = structlog.get_config()
    processors = config["processors"]
    assert any(isinstance(p, structlog.processors.JSONRenderer) for p in processors)


def test_configure_logging_console_selects_console_renderer() -> None:
    configure_logging(json_output=False)
    config = structlog.get_config()
    processors = config["processors"]
    assert any(isinstance(p, structlog.dev.ConsoleRenderer) for p in processors)


# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


def test_get_logger_returns_usable_bound_logger() -> None:
    configure_logging(json_output=False)
    logger = get_logger("test.logging")
    logger.info("smoke-test", key="value")  # must not raise
    assert callable(getattr(logger, "info", None))
    assert callable(getattr(logger, "warning", None))
    assert callable(getattr(logger, "error", None))
