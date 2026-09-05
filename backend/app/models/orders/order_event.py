"""`order_event` (S3 §3.2) — the append-only source of truth (ADR 7).

`OrderProjectionService` folds these by `seq` into `order`'s cached status/`filled_quantity`/
`average_fill_price`. Dedupe key for `fill` events is `execution_id`, never `order_id` (ADR 7 --
a partial fill produces many fills per order); every other event type leaves `execution_id` null.

**`seq` assignment.** Neither S3 §3.2 nor ADR 7 specifies how `seq` values are chosen, only that
folding must tolerate gaps and out-of-order *processing* (foundation spec §10 case 4). Two
concurrent outbox workers can process a `trade_updates`-derived `accepted` and a later `fill` for
the same order in either order (`JobOutboxRepository.claim_next`'s `SKIP LOCKED` guarantees one
*row* per worker, not one *order*'s events processed in arrival order) -- an incrementing "next
available integer" counter would then durably record them backwards. Deriving `seq` instead from
the event's own logical timestamp (epoch microseconds, UTC) makes it independent of processing
order: whichever event actually happened first at the broker gets the smaller `seq`, however the
two rows are inserted. `BigInteger`, not `Integer`: epoch-microsecond values already exceed
Postgres's 32-bit `int4` range today.
"""

from __future__ import annotations

import uuid
from datetime import (
    UTC,
    datetime,
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, BigInteger, DateTime, ForeignKey, String, UniqueConstraint, event, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.orders._enum import enum_values

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.uow import UnitOfWork


def seq_from_timestamp(ts: datetime) -> int:
    """Epoch microseconds (UTC) -- the ordering key every `order_event` writer uses (module
    docstring). A retried write naturally gets a fresh value, so a same-microsecond collision
    (theoretical; the unique constraint below would reject it) self-heals on retry rather than
    wedging the outbox row."""
    return int(ts.astimezone(UTC).timestamp() * 1_000_000)


class OrderEventType(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    FILL = "fill"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


class OrderEvent(Base):
    __tablename__ = "order_event"
    __table_args__ = (
        UniqueConstraint("order_id", "seq", name="uq_order_event_order_id_seq"),
        UniqueConstraint("execution_id", name="uq_order_event_execution_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("order.id"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[OrderEventType] = mapped_column(
        SQLAlchemyEnum(OrderEventType, name="order_event_type", values_callable=enum_values),
        nullable=False,
    )
    # Set only on `fill` events -- the dedupe key (module docstring, ADR 7). Nullable so
    # non-fill events (submitted/accepted/rejected/canceled/expired) simply omit it; the unique
    # constraint above only ever compares the non-null values Postgres actually sees.
    execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Append-only enforcement (ADR 7, matching journal_entry/posting's precedent, S1 §6): no
# UPDATE/DELETE grant for either runtime credential.
event.listen(
    OrderEvent.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON order_event FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class OrderEventRepository(BaseRepository[OrderEvent]):
    """No `customer_id_column`: `order_event` carries no customer identity of its own, matching
    `journal_entry`'s precedent (S1) -- per-customer reads go through `order`, which does carry
    `customer_id` and is ownership-checked at the controller before any `order_event` query."""

    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=OrderEvent)

    def list_for_order(self, order_id: uuid.UUID) -> Sequence[OrderEvent]:
        return (
            self.session.query(OrderEvent)
            .filter_by(order_id=order_id)
            .order_by(OrderEvent.seq)
            .all()
        )


__all__ = ["OrderEvent", "OrderEventRepository", "OrderEventType", "seq_from_timestamp"]
