"""`BaseRepository` (S0 §5, ADR 14): application-layer tenant scoping and the append-only guard.

Uses a throwaway entity registered on `app.models.base.Base`'s metadata, created and dropped by
this file alone — not a real model, which belongs to the wave that owns an actual aggregate.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

import pytest
from sqlalchemy import DateTime, String, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import AppendOnlyViolationError, BaseRepository
from app.core.uow import SessionRole, UnitOfWork
from app.core.watermark import Watermark
from app.extensions import DbRole, dispose_engines, init_engines
from app.models.base import Base

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy import Engine

    from app.config import Settings


@pytest.fixture(autouse=True)
def engines(test_settings: Settings) -> None:
    """Populates the engine registry `UnitOfWork`'s default session_factory needs."""
    init_engines(test_settings)
    yield None
    dispose_engines()


class Widget(Base):
    """Throwaway bitemporal, tenant-scoped entity for this test module."""

    __tablename__ = "repo_test_widget"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        postgresql.UUID(as_uuid=True), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)


class WidgetRepository(BaseRepository[Widget]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow,
            entity=Widget,
            customer_id_column=Widget.customer_id,
            recorded_at_column=Widget.recorded_at,
        )


class AppendOnlyWidgetRepository(BaseRepository[Widget]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Widget, customer_id_column=Widget.customer_id)


@pytest.fixture
def widget_table(owner_engine: Engine):
    # Table-scoped create/drop, not `create_all(tables=[...])`: the latter dispatches enum DDL
    # events for the whole shared metadata regardless of the `tables=` filter.
    Widget.__table__.create(bind=owner_engine, checkfirst=True)
    yield
    Widget.__table__.drop(bind=owner_engine, checkfirst=True)


T0 = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
T1 = T0 + timedelta(hours=1)


def _customer_uow(customer_id: uuid.UUID) -> UnitOfWork:
    return UnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.OWNER)


# --- tenant scoping --------------------------------------------------------------------------


def test_customer_session_only_sees_its_own_rows(widget_table: None) -> None:
    customer_a, customer_b = uuid.uuid4(), uuid.uuid4()

    with _customer_uow(customer_a) as uow:
        repo = WidgetRepository(uow)
        repo.add(Widget(customer_id=customer_a, recorded_at=T0, label="mine"))
        repo.add(Widget(customer_id=customer_b, recorded_at=T0, label="not mine"))
        uow.commit()

    with _customer_uow(customer_a) as uow:
        repo = WidgetRepository(uow)
        rows = repo.find_as_of(as_of=Watermark.live())
        assert {row.label for row in rows} == {"mine"}


def test_adviser_session_reads_across_customers(widget_table: None) -> None:
    customer_a, customer_b = uuid.uuid4(), uuid.uuid4()

    with _customer_uow(customer_a) as uow:
        repo = WidgetRepository(uow)
        repo.add(Widget(customer_id=customer_a, recorded_at=T0, label="a"))
        repo.add(Widget(customer_id=customer_b, recorded_at=T0, label="b"))
        uow.commit()

    with UnitOfWork(customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.OWNER) as uow:
        repo = WidgetRepository(uow)
        rows = repo.find_as_of(as_of=Watermark.live())
        assert {row.label for row in rows} == {"a", "b"}


# --- the as_of shape --------------------------------------------------------------------------


def test_find_as_of_respects_the_watermark(widget_table: None) -> None:
    customer_id = uuid.uuid4()

    with _customer_uow(customer_id) as uow:
        repo = WidgetRepository(uow)
        repo.add(Widget(customer_id=customer_id, recorded_at=T0, label="early"))
        repo.add(Widget(customer_id=customer_id, recorded_at=T1, label="late"))
        uow.commit()

    with _customer_uow(customer_id) as uow:
        repo = WidgetRepository(uow)
        as_published = repo.find_as_of(as_of=Watermark.as_published(T0))
        assert {row.label for row in as_published} == {"early"}

        live = repo.find_as_of(as_of=Watermark.live())
        assert {row.label for row in live} == {"early", "late"}


def test_find_as_of_requires_the_keyword_argument(widget_table: None) -> None:
    """Omitting `as_of` is a `TypeError` at runtime too, per ADR 6."""
    customer_id = uuid.uuid4()
    with _customer_uow(customer_id) as uow:
        repo = WidgetRepository(uow)
        with pytest.raises(TypeError):
            repo.find_as_of()  # type: ignore[call-arg]


def test_find_as_of_without_a_recorded_at_column_is_a_clear_error(widget_table: None) -> None:
    customer_id = uuid.uuid4()
    with _customer_uow(customer_id) as uow:
        repo = AppendOnlyWidgetRepository(uow)
        with pytest.raises(RuntimeError, match="recorded_at_column"):
            repo.find_as_of(as_of=Watermark.live())


# --- append-only guard ---------------------------------------------------------------------------


def test_append_only_repository_allows_insert(widget_table: None) -> None:
    customer_id = uuid.uuid4()
    with _customer_uow(customer_id) as uow:
        repo = AppendOnlyWidgetRepository(uow)
        repo.add(Widget(customer_id=customer_id, recorded_at=T0, label="new"))
        uow.commit()  # must not raise

    with _customer_uow(customer_id) as uow:
        rows = WidgetRepository(uow).find_as_of(as_of=Watermark.live())
        assert {row.label for row in rows} == {"new"}


def test_append_only_repository_rejects_update(widget_table: None) -> None:
    customer_id = uuid.uuid4()
    with _customer_uow(customer_id) as uow:
        original = Widget(customer_id=customer_id, recorded_at=T0, label="original")
        WidgetRepository(uow).add(original)
        uow.commit()

    with _customer_uow(customer_id) as uow:
        repo = AppendOnlyWidgetRepository(uow)
        widget = repo.session.execute(select(Widget)).scalars().one()
        widget.label = "mutated"
        with pytest.raises(AppendOnlyViolationError):
            uow.session.flush()


def test_append_only_repository_rejects_delete(widget_table: None) -> None:
    customer_id = uuid.uuid4()
    with _customer_uow(customer_id) as uow:
        doomed = Widget(customer_id=customer_id, recorded_at=T0, label="doomed")
        WidgetRepository(uow).add(doomed)
        uow.commit()

    with _customer_uow(customer_id) as uow:
        repo = AppendOnlyWidgetRepository(uow)
        widget = repo.session.execute(select(Widget)).scalars().one()
        repo.session.delete(widget)
        with pytest.raises(AppendOnlyViolationError):
            uow.session.flush()


# --- Dependency Inversion: services depend on a Protocol, never this class directly --------------


class WidgetRepositoryProtocol(Protocol):
    def find_as_of(self, *, as_of: Watermark) -> Sequence[Widget]: ...


class _FakeWidgetRepository:
    """In-memory fake substituted purely by shape, no database or `UnitOfWork`."""

    def __init__(self, widgets: Sequence[Widget]) -> None:
        self._widgets = widgets

    def find_as_of(self, *, as_of: Watermark) -> Sequence[Widget]:
        return [w for w in self._widgets if w.recorded_at <= as_of.cutoff]


def _labels_visible(repo: WidgetRepositoryProtocol, *, as_of: Watermark) -> set[str]:
    """Stands in for a service method, depending on the Protocol, not `BaseRepository`."""
    return {widget.label for widget in repo.find_as_of(as_of=as_of)}


def test_a_fake_repository_substitutes_for_the_real_one_via_the_protocol() -> None:
    fake = _FakeWidgetRepository(
        [
            Widget(customer_id=uuid.uuid4(), recorded_at=T0, label="early"),
            Widget(customer_id=uuid.uuid4(), recorded_at=T1, label="late"),
        ]
    )
    assert _labels_visible(fake, as_of=Watermark.as_published(T0)) == {"early"}
    assert _labels_visible(fake, as_of=Watermark.live()) == {"early", "late"}
