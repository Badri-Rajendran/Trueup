"""`UnitOfWork` — the transaction boundary (S0 §5, ADR 14).

One instance per HTTP request, one per job execution step. A service method either fully succeeds
and commits **once** through the `UnitOfWork` it was handed, or raises and the whole unit rolls
back — no service ever opens its own transaction or calls `session.commit()` directly.

**Tenant context is passed in explicitly, never read from `flask.g`.** `UnitOfWork(customer_id=...,
role=...)` is a plain constructor call that works identically inside a request, inside a scheduled
job, and inside a unit test — none of which can assume a Flask request context exists. A `core`
module reaching into a web-framework global would make the entire persistence layer untestable
outside a request and would quietly couple jobs to Flask.

At the start of every transaction this issues `SELECT set_config('app.role', ..., true)` and
`SELECT set_config('app.customer_id', ..., true)` — the `true` (`is_local`) argument is
`set_config`'s parameterized equivalent of `SET LOCAL`: transaction-scoped, and gone the instant
the transaction ends, which is exactly what S0 §7.3's RLS policies rely on. `set_config` is used
instead of a literal `SET LOCAL app.role = '...'` string specifically so the value is a bound
parameter, never string-interpolated SQL (root `CLAUDE.md`: parameterized queries only).

**Extending `UnitOfWork` with repositories.** This module intentionally ships zero repository
accessors — `uow.ledger`, `uow.orders`, and the rest belong to the wave that defines each
aggregate's repository. The extension point is ordinary subclassing plus `functools.cached_property`
bound to `self.session`, so each accessor is fully typed and mypy-checked, with no registry, no
string keys, and no dynamic attribute magic to work around:

    class LedgerUnitOfWork(UnitOfWork):
        @cached_property
        def ledger(self) -> LedgerRepository:
            return SqlLedgerRepository(self)

    with LedgerUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        uow.ledger.post(entry)
        uow.commit()
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
    """The business role behind the current session — what S0 §7.3's RLS policy reads as
    `app.role`. Distinct from `DbRole` (`app/core/db.py`), which selects a *database
    credential*: a customer, an adviser, and an admin all authenticate through the same `APP`
    database role, and RLS is what tells their traffic apart at the row level.
    """

    CUSTOMER = "customer"
    ADVISER = "adviser"
    ADMIN = "admin"


class UnitOfWork:
    """The transaction boundary. See module docstring for the extension mechanism.

    Not reentrant: one instance is good for exactly one `with` block, matching "one per request,
    one per job step" — reusing an instance across two transactions would let a repository cached
    on it silently keep operating against an already-closed session.
    """

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
                # Never commit implicitly: an exception, a missed commit(), and a plain fall-through
                # all end the same way — rolled back.
                session.rollback()
        finally:
            session.close()
            self._session = None

    def commit(self) -> None:
        """Commit the transaction. Called at most once, and only after every write in this unit
        has succeeded — S0 §5's "exactly one commit point per operation"."""
        self.session.commit()
        self._finalized = True

    def rollback(self) -> None:
        """Explicitly discard the transaction. Rarely needed directly — raising is the normal way
        to trigger a rollback — but available for a service that decides mid-operation that its
        own work should not proceed without treating that decision as an error."""
        self.session.rollback()
        self._finalized = True
