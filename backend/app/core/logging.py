"""Structured logging and per-request correlation IDs (S0 §7.4, OWASP A09).

One correlation ID per request, echoed on the response and attached to every log line emitted
while handling it, so a customer report can be joined to the exact server-side trace.

Secrets and PII never reach a log (root `CLAUDE.md`). This module provides the plumbing; keeping
payloads out of log calls is the caller's responsibility, and `views/` schemas are the enforcement
point for what leaves the process at all.
"""

from __future__ import annotations

import logging
import uuid
from contextvars import ContextVar
from typing import Any

import structlog

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)

CORRELATION_HEADER = "X-Correlation-ID"


def new_correlation_id() -> str:
    return str(uuid.uuid4())


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def _add_correlation_id(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    correlation_id = get_correlation_id()
    if correlation_id is not None:
        event_dict["correlation_id"] = correlation_id
    return event_dict


def configure_logging(*, json_output: bool, level: int = logging.INFO) -> None:
    """Configure structlog once at startup.

    JSON in deployed environments so Application Insights can index fields (ADR 20); a readable
    console renderer in development, where a human is the consumer.
    """
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
