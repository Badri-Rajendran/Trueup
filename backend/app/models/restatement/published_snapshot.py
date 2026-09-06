"""`published_snapshot` (S6 §3.1, ADR 6) — the immutable, as-published figure a period close ever
actually showed a customer.

Append-only, RLS-scoped by `customer_id`, matching `daily_close`/`sub_period_return`'s posture
(S4 §3.1/§3.5): a snapshot is never corrected in place -- a later restatement changes the *live*
figure, never this row, and `SnapshotService.cross_check` (`app/services/restatement/
snapshot_service.py`) is what proves that holds forever (ADR 6's tamper-detection invariant).
"""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    date,
    datetime,
)
from decimal import Decimal  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date as SQLAlchemyDate
from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class PublishedSnapshot(Base):
    __tablename__ = "published_snapshot"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    period_start: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    period_end: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    # The `recorded_at` cutoff this snapshot is pinned to (ADR 1/6) -- distinct from `published_at`
    # below, which is wall-clock publication time. This implementation captures both from the same
    # database `now()` at publication (`SnapshotService.publish`), so they coincide by
    # construction; a future asynchronous publication pipeline could let them diverge.
    publish_watermark: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Wider than Money's 4dp, matching `sub_period_return.return_pct` -- a ratio, not a money
    # dimension (ADR 16 deliberately does not cover it).
    twr: Mapped[Decimal] = mapped_column(Numeric(18, 10), nullable=False)
    balance: Mapped[Money] = mapped_column(MoneyType, nullable=False)
    holdings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class PublishedSnapshotRepository(BaseRepository[PublishedSnapshot]):
    """Append-only (S6 §3.1: "No UPDATE/DELETE grant, same append-only posture as
    `journal_entry`"). Tenant-scoped by `customer_id` for a customer session; an adviser/admin
    session (`list_all`, the periodic cross-check sweep) reads whole-book, matching every other
    admin/worker-role job query in this codebase."""

    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(
            uow, entity=PublishedSnapshot, customer_id_column=PublishedSnapshot.customer_id
        )

    def list_for_customer(self, customer_id: uuid.UUID) -> list[PublishedSnapshot]:
        """`GET /api/v1/statements` (S6 §8) -- every snapshot ever published for this customer,
        including every watermark a period was republished under (FR-26: each one must stay
        independently queryable)."""
        return (
            self.session.query(PublishedSnapshot)
            .filter_by(customer_id=customer_id)
            .order_by(
                PublishedSnapshot.period_start.desc(), PublishedSnapshot.publish_watermark.desc()
            )
            .all()
        )

    def latest_for_period(
        self, customer_id: uuid.UUID, period_start: date
    ) -> PublishedSnapshot | None:
        """`GET /api/v1/statements/<period>` (S6 §8) with no explicit watermark -- the most
        recently published snapshot for this `period_start`."""
        return (
            self.session.query(PublishedSnapshot)
            .filter_by(customer_id=customer_id, period_start=period_start)
            .order_by(PublishedSnapshot.publish_watermark.desc())
            .first()
        )

    def at_watermark_for_period(
        self, customer_id: uuid.UUID, period_start: date, publish_watermark: datetime
    ) -> PublishedSnapshot | None:
        """The specific snapshot a caller names by its own `publish_watermark` (S6 §7: "never a
        raw timestamp typed by a caller" other than one obtained from this same table via
        `list_for_customer`)."""
        return (
            self.session.query(PublishedSnapshot)
            .filter_by(
                customer_id=customer_id,
                period_start=period_start,
                publish_watermark=publish_watermark,
            )
            .first()
        )

    def list_touching(self, customer_id: uuid.UUID, on_date: date) -> list[PublishedSnapshot]:
        """Every already-published snapshot whose `[period_start, period_end]` spans `on_date`
        (S6 §6: `cross_check` runs automatically, after every `restate()`, against every
        already-published period the restatement touched)."""
        return (
            self.session.query(PublishedSnapshot)
            .filter(
                PublishedSnapshot.customer_id == customer_id,
                PublishedSnapshot.period_start <= on_date,
                PublishedSnapshot.period_end >= on_date,
            )
            .all()
        )

    def list_all(self) -> list[PublishedSnapshot]:
        """Whole-book listing for the periodic cross-check sweep job -- admin/worker-role only
        (`_tenant_scoped` would raise this under a customer session, by design)."""
        return self.session.query(PublishedSnapshot).all()


__all__ = ["PublishedSnapshot", "PublishedSnapshotRepository"]
