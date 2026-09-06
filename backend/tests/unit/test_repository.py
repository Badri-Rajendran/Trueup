"""`BaseRepository._tenant_scoped()`: pure statement-building, no database (S0 §5, ADR 14).
Must fail loudly when called on a repository with no `customer_id_column` configured."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.core.uow import SessionRole, UnitOfWork
from app.models.base import Base


class _Gizmo(Base):
    """Throwaway entity for this module's `_tenant_scoped()` tests, never created in a database."""

    __tablename__ = "repo_unit_test_gizmo"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(postgresql.UUID(as_uuid=True), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)


class _ScopedGizmoRepository(BaseRepository[_Gizmo]):
    """Genuinely customer-scoped repository; the regression case that must keep filtering."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=_Gizmo, customer_id_column=_Gizmo.customer_id)


class _UnscopedGizmoRepository(BaseRepository[_Gizmo]):
    """Stands in for a table with no customer identity, so no `customer_id_column` is configured."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=_Gizmo)


def _customer_uow(customer_id: uuid.UUID) -> UnitOfWork:
    """Never entered: `_tenant_scoped()` only reads `.role`/`.customer_id`, plain properties."""
    return UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER)


def test_tenant_scoped_without_a_customer_id_column_raises_clearly() -> None:
    repo = _UnscopedGizmoRepository(_customer_uow(uuid.uuid4()))
    with pytest.raises(RuntimeError, match="customer_id_column"):
        repo._tenant_scoped(select(_Gizmo))


def test_tenant_scoped_with_a_customer_id_column_still_filters_by_it() -> None:
    customer_id = uuid.uuid4()
    repo = _ScopedGizmoRepository(_customer_uow(customer_id))

    statement = repo._tenant_scoped(select(_Gizmo))

    compiled = statement.compile()
    assert "customer_id" in str(compiled)
    assert customer_id in compiled.params.values()
