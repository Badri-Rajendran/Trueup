"""Structured logging and correlation-ID plumbing (S0 §7.4, OWASP A09).

The correlation ID is the join key between a customer's bug report and the server-side trace.
These tests verify the plumbing: generation, context-variable storage, processor injection,
renderer selection, and logger usability.

No ``unittest.mock.Mock`` — all assertions are against real structlog / contextvars behaviour.
"""

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
    # Must parse without raising — validates format and version.
    parsed = uuid.UUID(cid)
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
    """A context that has never called ``set_correlation_id`` must read ``None``, not crash."""
    # contextvars.Context() creates a truly empty context (no inherited values), unlike
    # copy_context() which copies the current context's ContextVar values.
    ctx = contextvars.Context()
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
    """When no correlation ID is set, the key must be *absent* — not present with a ``None``
    value — so downstream consumers (JSON serializer, Application Insights) never see a null
    ``correlation_id`` field."""
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
    # Emitting a line must not raise. We don't assert on output content — the processors may
    # change — only that the returned object is usable and structlog-typed.
    logger.info("smoke-test", key="value")
    # structlog.get_logger returns a BoundLoggerLazyProxy; verify it quacks like a bound logger.
    assert callable(getattr(logger, "info", None))
    assert callable(getattr(logger, "warning", None))
    assert callable(getattr(logger, "error", None))
