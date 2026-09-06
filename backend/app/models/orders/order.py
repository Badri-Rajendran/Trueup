"""`order` (S3 §3.1) — the rebuildable projection (ADR 7).

`assert projection == fold(order_event)` is the standing invariant for everything `order_event`'s
`event_type` enum actually covers (`submitted` onward — `OrderProjectionService`). The
pre-submission portion of the lifecycle (`draft` -> `awaiting_approval` -> `approved`) has no
corresponding `event_type` (S3 §3.2's enum starts at `submitted`) because nothing external drives
it — it is written directly by `OrderService` as the customer/S9 caller and the approval endpoint
act, exactly as `journal_entry`/`posting` are the append-only truth while `account` is a plain
mutable row (S1 precedent, reused here for the same shape of problem).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, String, event, func, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Price, PriceType, Units, UnitsType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.orders._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(StrEnum):
    """S3 §4's state machine. `draft` is the transient pre-persistence value used only as the
    `_write` starting point below; every row actually committed lands in `awaiting_approval` or
    `approved` at the earliest (`OrderService.create_order` never leaves a row at `draft`)."""

    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    REJECTED = "rejected"
    CANCELED = "canceled"
    EXPIRED = "expired"


TERMINAL_NON_FILLED_STATUSES = frozenset(
    {OrderStatus.REJECTED, OrderStatus.CANCELED, OrderStatus.EXPIRED}
)
"""FR-38's "terminal non-filled state" set — the trigger for `ApprovalHoldService.release`."""


def derive_client_order_id(order_id: uuid.UUID) -> str:
    """S3 §3.1/§5: deterministic, derived from `order.id`, never regenerated on retry — a network
    timeout on the broker `POST` can be safely retried with this same value (foundation §10 case
    2). A pure function so every caller (order creation, a retried outbox attempt) computes the
    identical string with no state to keep in sync.
    """
    return f"trueup-{order_id}"


class Order(Base):
    __tablename__ = "order"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    # No FK: the securities catalogue is S5's to define (matches `account.security_id`'s
    # precedent, S1 §3.1).
    security_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    side: Mapped[OrderSide] = mapped_column(
        SQLAlchemyEnum(OrderSide, name="order_side", values_callable=enum_values), nullable=False
    )
    quantity_requested: Mapped[Units] = mapped_column(UnitsType, nullable=False)
    status: Mapped[OrderStatus] = mapped_column(
        SQLAlchemyEnum(OrderStatus, name="order_status", values_callable=enum_values),
        nullable=False,
        default=OrderStatus.DRAFT,
    )
    filled_quantity: Mapped[Units] = mapped_column(
        UnitsType, nullable=False, default=Units("0")
    )
    average_fill_price: Mapped[Price | None] = mapped_column(PriceType, nullable=True)
    client_order_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


# S0 §7.3's role-aware tenant-isolation RLS policy (ADR 17) — `order` carries a native
# `customer_id`, same shape as `account`/`customer`.
event.listen(
    Order.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE "order" ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON "order"
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    Order.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        'DROP POLICY IF EXISTS tenant_isolation ON "order";'
        'ALTER TABLE "order" DISABLE ROW LEVEL SECURITY;'
    ),
)


class OrderRepository(BaseRepository[Order]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Order, customer_id_column=Order.customer_id)

    def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        return self.session.query(Order).filter_by(id=order_id).first()

    def get_for_update(self, order_id: uuid.UUID) -> Order | None:
        """`SELECT ... FOR UPDATE`, serializing concurrent processors of this order's events —
        the per-order analogue of `customer_cash_lock.acquire` (S1 §3.5), needed because two
        `order_event`s for the same order can be claimed by two different outbox workers at once
        (`JobOutboxRepository.claim_next`'s `SKIP LOCKED` only guarantees one *row* per worker,
        not one *order* per worker)."""
        statement = self._tenant_scoped(select(Order)).where(Order.id == order_id).with_for_update()
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_client_order_id(self, client_order_id: str) -> Order | None:
        return self.session.query(Order).filter_by(client_order_id=client_order_id).first()

    def list_for_customer(self, customer_id: uuid.UUID) -> list[Order]:
        statement = (
            self._tenant_scoped(select(Order))
            .where(Order.customer_id == customer_id)
            .order_by(Order.created_at.desc())
        )
        return list(self.session.execute(statement).scalars().all())

    def open_buy_orders(self, customer_id: uuid.UUID) -> list[Order]:
        """Buy orders past the approval-hold window but not yet resolved (S1 §5's
        `open_buy_commitments` -- CashPolicyService's contract, owned here)."""
        statement = self._tenant_scoped(select(Order)).where(
            Order.customer_id == customer_id,
            Order.side == OrderSide.BUY,
            Order.status.in_(
                (OrderStatus.SUBMITTED, OrderStatus.ACCEPTED, OrderStatus.PARTIALLY_FILLED)
            ),
        )
        return list(self.session.execute(statement).scalars().all())


__all__ = [
    "TERMINAL_NON_FILLED_STATUSES",
    "Order",
    "OrderRepository",
    "OrderSide",
    "OrderStatus",
    "derive_client_order_id",
]
