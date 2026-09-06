"""Database role and session-factory resolution — the vocabulary, not the wiring.

`app/core/` imports nothing else under `app/` (S0 §3), so it cannot reach into `app/extensions.py`
for a session. But `UnitOfWork` lives in core and needs one. The dependency is therefore inverted
exactly as `core/crypto.py` inverts the cipher: core declares the concept and a registry, and
`app/extensions.py` registers the concrete implementation at startup.

`DbRole` lives here rather than in `extensions.py` because it is a domain concept, not an
extension instance: which credential a transaction runs under is the mechanism behind S0 §7.3's
rule that bypassing Row-Level Security is a credential boundary rather than application
discipline. `extensions.py` re-exports it, so callers outside core need not know it moved.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session


class DbRole(StrEnum):
    """Which database credential a connection uses. Not interchangeable."""

    APP = "app"
    """The web API. No BYPASSRLS. Every request-scoped UnitOfWork uses this."""

    WORKER = "worker"
    """Scheduled jobs and the outbox worker, which legitimately span every customer."""

    OWNER = "owner"
    """Schema owner. Migrations only; never serves a request."""

    CHAT = "chat"
    """S11's `execute_read_only_sql` tool only (ADR 19). A separate least-privilege credential —
    granted `SELECT` on the curated chat views alone, nothing else — so a validator bug or a
    successful prompt injection cannot reach beyond what this role can already see, independent
    of `APP`'s own (broader) grants."""


class SessionFactoryResolver(Protocol):
    """Returns a callable that opens a new `Session` bound to the given role's credential."""

    def __call__(self, role: DbRole) -> Callable[[], Session]: ...


class SessionFactoryNotConfiguredError(RuntimeError):
    """Raised when a UnitOfWork is opened before the application registered its engines.

    The failure mode must be a loud error at the transaction boundary, never a silent fallback to
    some default connection — a UnitOfWork running under the wrong credential would defeat the
    RLS boundary the roles exist to enforce.
    """


_resolver: SessionFactoryResolver | None = None


def set_session_factory_resolver(resolver: SessionFactoryResolver) -> None:
    """Install the process-wide resolver. Called by `app.extensions.init_engines`."""
    global _resolver
    _resolver = resolver


def reset_session_factory_resolver() -> None:
    """Clear the resolver. Used by tests and `dispose_engines`; never in request handling."""
    global _resolver
    _resolver = None


def resolve_session_factory(role: DbRole) -> Callable[[], Session]:
    if _resolver is None:
        raise SessionFactoryNotConfiguredError(
            "No session factory resolver installed. Call app.extensions.init_engines() during "
            "application startup before opening a UnitOfWork."
        )
    return _resolver(role)
