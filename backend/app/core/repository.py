"""`BaseRepository` — application-layer tenant scoping and the append-only guard (S0 §5, ADR 14).

Belt-and-suspenders above the database: tenant scoping filters every query by
`UnitOfWork.customer_id` (adviser/admin sessions skip it, FR-31/ADR 17), and `append_only = True`
rejects an UPDATE/DELETE before flush (S1 §6, ADR 17). `find_as_of()`'s `as_of` is required
keyword-only with no default (ADR 6).
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
    """Raised when an UPDATE or DELETE is about to be flushed for an append-only aggregate."""


class BaseRepository[ModelT]:
    """One instance per aggregate, bound to one `UnitOfWork`. See module docstring."""

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
        """Generic bitemporal, tenant-scoped read, e.g. `find_as_of(as_of=wm, order_id=id)`."""
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
        """Apply the customer filter. Adviser/admin sessions skip it deliberately (FR-31)."""
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
        """`before_flush` handler, registered only when `append_only` is `True`. Inspects
        `session.dirty`/`session.deleted` so no code path can mutate this row."""
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
