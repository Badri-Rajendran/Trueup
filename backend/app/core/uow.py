"""`UnitOfWork` — the transaction boundary (S0 §5, ADR 14).

One instance per HTTP request/job step; commits **once** or rolls back on raise. Tenant context is
passed in explicitly, never read from `flask.g`. Issues `SELECT set_config('app.role'/'app.customer_id',
..., true)` (`SET LOCAL`-equivalent, bound parameter) for S0 §7.3's RLS policies. Subclasses add
repository accessors via `functools.cached_property` bound to `self.session`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Self

from sqlalchemy import text

from app.core.db import DbRole, resolve_session_factory

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable
    from types import TracebackType

    from sqlalchemy.orm import Session


class SessionRole(StrEnum):
    """The business role behind the current session — what S0 §7.3's RLS policy reads as `app.role`.
    Distinct from `DbRole` (`app/core/db.py`), which selects a database credential."""

    CUSTOMER = "customer"
    ADVISER = "adviser"
    ADMIN = "admin"


class UnitOfWork:
    """The transaction boundary. See module docstring. Not reentrant: one instance per `with` block."""

    def __init__(
        self,
        *,
        customer_id: uuid.UUID | None,
        role: SessionRole,
        db_role: DbRole = DbRole.APP,
        session_factory: Callable[[], Session] | None = None,
    ) -> None:
        if role is SessionRole.CUSTOMER and customer_id is None:
            raise ValueError(
                "a customer-role UnitOfWork requires a customer_id; adviser/admin sessions may "
                "omit it because RLS's role branch, not customer_id, is what admits their reads"
            )
        self._customer_id = customer_id
        self._role = role
        self._db_role = db_role
        self._session_factory = session_factory
        self._session: Session | None = None
        self._entered = False
        self._finalized = False

    @property
    def customer_id(self) -> uuid.UUID | None:
        return self._customer_id

    @property
    def role(self) -> SessionRole:
        return self._role

    @property
    def db_role(self) -> DbRole:
        return self._db_role

    @property
    def session(self) -> Session:
        """The active session. Only valid inside the `with` block that opened it."""
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork.session accessed outside an active `with` block; enter the unit of "
                "work before using it"
            )
        return self._session

    def __enter__(self) -> Self:
        if self._entered:
            raise RuntimeError(
                "UnitOfWork is not reentrant; construct a new instance per transaction"
            )
        self._entered = True
        factory = self._session_factory or resolve_session_factory(self._db_role)
        self._session = factory()
        self._session.execute(
            text("SELECT set_config('app.role', :role, true)"),
            {"role": self._role.value},
        )
        self._session.execute(
            text("SELECT set_config('app.customer_id', :customer_id, true)"),
            {"customer_id": str(self._customer_id) if self._customer_id is not None else ""},
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        session = self.session
        try:
            if not self._finalized:
                # Never commit implicitly.
                session.rollback()
        finally:
            session.close()
            self._session = None

    def commit(self) -> None:
        """Commit the transaction. Called at most once — S0 §5's "exactly one commit point"."""
        self.session.commit()
        self._finalized = True

    def rollback(self) -> None:
        """Explicitly discard the transaction. Rarely needed directly — raising triggers rollback."""
        self.session.rollback()
        self._finalized = True
