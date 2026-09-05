"""Database role and session-factory resolution (S0 §7.3, ADR 14).

Ensures the credential boundary is strictly maintained and that a failure to configure
the process-wide resolver fails loudly rather than falling back to a default connection.
"""

from __future__ import annotations

from collections.abc import Callable, Generator

import pytest
from sqlalchemy.orm import Session

from app.core.db import (
    DbRole,
    SessionFactoryNotConfiguredError,
    reset_session_factory_resolver,
    resolve_session_factory,
    set_session_factory_resolver,
)


@pytest.fixture(autouse=True)
def _reset_resolver() -> Generator[None, None, None]:
    """Ensure tests start and end with a clean global state."""
    reset_session_factory_resolver()
    yield
    reset_session_factory_resolver()


class FakeResolver:
    """A test double that records which role it was asked to resolve."""

    def __init__(self) -> None:
        self.resolved_roles: list[DbRole] = []

    def __call__(self, role: DbRole) -> Callable[[], Session]:
        self.resolved_roles.append(role)
        return Session


def test_db_role_has_three_stable_values() -> None:
    """The database credential boundaries exist to enforce RLS (S0 §7.3)."""
    assert DbRole.APP.value == "app"
    assert DbRole.WORKER.value == "worker"
    assert DbRole.OWNER.value == "owner"


def test_resolve_without_configuration_raises_error() -> None:
    """A missing resolver must fail loudly to avoid silent fallback to a wrong credential."""
    with pytest.raises(SessionFactoryNotConfiguredError, match="No session factory resolver"):
        resolve_session_factory(DbRole.APP)


def test_resolve_delegates_to_registered_resolver() -> None:
    """The resolver must accurately pass the requested role down to the registered factory."""
    resolver = FakeResolver()
    set_session_factory_resolver(resolver)

    factory = resolve_session_factory(DbRole.WORKER)
    assert factory is Session
    assert resolver.resolved_roles == [DbRole.WORKER]


def test_reset_clears_registered_resolver() -> None:
    """Clearing the resolver must return the system to its unconfigured state."""
    resolver = FakeResolver()
    set_session_factory_resolver(resolver)

    reset_session_factory_resolver()

    with pytest.raises(SessionFactoryNotConfiguredError):
        resolve_session_factory(DbRole.APP)
