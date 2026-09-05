"""`BaseRepository` — application-layer tenant scoping and the append-only guard (S0 §5, ADR 14).

Two independent defenses this module provides, both belt-and-suspenders above the database:

- **Tenant scoping.** Every query a repository builds is filtered by the `customer_id` carried on
  its `UnitOfWork` — taken from there, never from a Flask global (`app/core/uow.py`). This is the
  *application-layer* half of S0 §7.3's defense-in-depth; Postgres RLS is the control that still
  holds if this code is bypassed or buggy, and this is the control that fails fast, before a query
  is even sent, for the common case. An adviser/admin session (`SessionRole.ADVISER`/`ADMIN`) skips
  the filter deliberately — FR-31's cross-customer reconciliation screen needs exactly that, and
  RLS's role-aware policy (ADR 17) is what still gates it at the database. `customer_id_column` is
  optional: a table with no customer identity at all (`inbound_event`, `job_outbox`, `job_run` —
  internal operational/audit tables, not customer data) omits it, and `_tenant_scoped()` raises
  rather than building a nonsense filter if such a repository ever calls it.
- **Append-only enforcement.** A repository subclass for an append-only aggregate (`journal_entry`,
  `posting`, `order_event`, `published_snapshot`, ...) sets `append_only = True`, and an UPDATE or
  DELETE about to be flushed for that entity is rejected before it reaches the database — the
  ORM-layer half of the guarantee S1 §6's revoked grants and ADR 17's deferred balance trigger
  backstop at the database. Three independent layers for the one invariant this ledger cannot get
  wrong (NFR-1, NFR-2).

**The `as_of: Watermark` shape.** `find_as_of()` is built the way ADR 6 requires every bitemporal
read to be: `as_of` is required and keyword-only, with no default, so a caller who forgets it gets a
`TypeError` before the code ships, not a live figure silently mislabelled as published. A repository
for an aggregate with no bitemporal dimension simply never calls this method — it exists here to be
inherited and to fix the shape Wave 3's ledger repositories reuse, not to be imposed on everything.

Services depend on their aggregate's own `Protocol` (the same pattern S0 §5 uses in
`integrations/ports.py`), never on `BaseRepository` directly — a test substitutes a fake by
implementing that Protocol structurally, with no import of this module at all.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from sqlalchemy import event, select

from app.core.uow import SessionRole

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import datetime

    from sqlalchemy import Select
    from sqlalchemy.orm import InstrumentedAttribute, Session

    from app.core.uow import UnitOfWork
    from app.core.watermark import Watermark


class AppendOnlyViolationError(RuntimeError):
    """Raised when an UPDATE or DELETE is about to be flushed for an append-only aggregate.

    The database is the guarantee of record (S1 §6's revoked grants, ADR 17's deferred balance
    trigger); this catches the same mistake one layer earlier, in the application, before the
    statement is even sent.
    """


class BaseRepository[ModelT]:
    """One instance per aggregate, bound to one `UnitOfWork`. See module docstring.

    Subclasses pass their entity type and tenant/watermark columns to `__init__` — a repository is
    generic over any mapped entity, not tied to a particular one via inheritance-time
    parameterization, which keeps this class usable by an entity `app/core` has never heard of.
    """

    append_only: ClassVar[bool] = False
    """Set `True` on an aggregate's repository subclass to forbid UPDATE/DELETE (ADR 1, S1 §6)."""

    def __init__(
        self,
        uow: UnitOfWork,
        *,
        entity: type[ModelT],
        customer_id_column: InstrumentedAttribute[Any] | None = None,
        recorded_at_column: InstrumentedAttribute[datetime] | None = None,
    ) -> None:
        self._uow = uow
        self._entity = entity
        self._customer_id_column = customer_id_column
        self._recorded_at_column = recorded_at_column
        if self.append_only:
            event.listen(self.session, "before_flush", self._reject_mutation)

    @property
    def session(self) -> Session:
        return self._uow.session

    def add(self, instance: ModelT) -> None:
        """Stage a new row. INSERT is how an append-only aggregate grows — never blocked here."""
        self.session.add(instance)

    def find_as_of(self, *, as_of: Watermark, **equality_filters: Any) -> Sequence[ModelT]:
        """Generic bitemporal, tenant-scoped read. `as_of` has no default — see module docstring.

        `equality_filters` are plain `column=value` matches against the entity, e.g.
        `find_as_of(as_of=watermark, order_id=order_id)`. A concrete repository with a richer
        query shape overrides or wraps this rather than forcing every read through it.
        """
        if self._recorded_at_column is None:
            raise RuntimeError(
                f"{type(self).__name__} was not configured with a recorded_at_column; "
                "find_as_of() is only for bitemporally-sensitive aggregates"
            )
        statement = self._tenant_scoped(select(self._entity))
        statement = statement.where(self._recorded_at_column <= as_of.cutoff)
        for field, value in equality_filters.items():
            statement = statement.where(getattr(self._entity, field) == value)
        return self.session.execute(statement).scalars().all()

    def _tenant_scoped(self, statement: Select[tuple[ModelT]]) -> Select[tuple[ModelT]]:
        """Apply the customer filter every subclass query should build on.

        Adviser/admin sessions read across customers deliberately (FR-31); RLS's role-aware policy
        is what actually gates that at the database (ADR 17), not this method.
        """
        if self._uow.role in (SessionRole.ADVISER, SessionRole.ADMIN):
            return statement
        if self._customer_id_column is None:
            raise RuntimeError(
                f"{type(self).__name__} has no customer_id_column configured; it cannot be "
                "tenant-scoped — this repository is for a table with no customer identity"
            )
        customer_id = self._uow.customer_id
        if customer_id is None:  # pragma: no cover - UnitOfWork already guarantees this
            raise RuntimeError(
                "a customer-scoped repository query requires a customer_id on the UnitOfWork"
            )
        return statement.where(self._customer_id_column == customer_id)

    def _reject_mutation(self, session: Session, flush_context: Any, instances: Any) -> None:
        """`before_flush` handler, registered only when `append_only` is `True`.

        Inspects `session.dirty`/`session.deleted` rather than intercepting a repository method,
        because the guarantee this exists for is "no code path can mutate this row" — including one
        that reaches the entity through a different repository, or through a plain
        `session.add(existing_instance)` after changing an attribute.
        """
        for obj in session.dirty:
            if isinstance(obj, self._entity):
                raise AppendOnlyViolationError(
                    f"{type(obj).__name__} is append-only; update is not permitted (ADR 1)"
                )
        for obj in session.deleted:
            if isinstance(obj, self._entity):
                raise AppendOnlyViolationError(
                    f"{type(obj).__name__} is append-only; delete is not permitted (ADR 1)"
                )
