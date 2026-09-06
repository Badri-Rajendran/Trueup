"""`ApprovalHoldService` (S3 §3.3/§4) — opens and releases the cash hold behind an order's
approval-pending/approved-not-yet-submitted window.

`release()` is idempotent by design (S3 §7 case 5): a `rejected`/`canceled`/`expired`/`submitted`
event for an order with no active hold (already released, or never held because it was below
threshold) is a no-op, never an error that could block folding the event that triggered it. Every
caller runs this inside the same `UnitOfWork`/transaction as the `order_event` insert and the
`order` projection update it accompanies (FR-38) — this service never opens its own transaction or
commits.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.orders.approval_hold import (
    ApprovalHold,
    ApprovalHoldReleaseReason,
    ApprovalHoldStatus,
)

if TYPE_CHECKING:
    import uuid
    from datetime import datetime

    from app.core.money import Money
    from app.services.orders.uow import OrdersUnitOfWork


class ApprovalHoldService:
    def __init__(self, uow: OrdersUnitOfWork) -> None:
        self._uow = uow

    def open(
        self, *, order_id: uuid.UUID, customer_id: uuid.UUID, amount_money: Money
    ) -> ApprovalHold:
        """Create the one hold row an order will ever have (`order_id` is unique, S3 §3.3).
        Callers acquire the per-customer cash lock (S1 §3.5) before calling this, in the same
        transaction, per foundation spec §10 case 1."""
        hold = ApprovalHold(order_id=order_id, customer_id=customer_id, amount_money=amount_money)
        self._uow.approval_holds.add(hold)
        return hold

    def release(
        self,
        order_id: uuid.UUID,
        reason: ApprovalHoldReleaseReason,
        *,
        released_at: datetime,
    ) -> None:
        hold = self._uow.approval_holds.get_by_order_id(order_id)
        if hold is None or hold.status is ApprovalHoldStatus.RELEASED:
            return
        hold.status = ApprovalHoldStatus.RELEASED
        hold.released_at = released_at
        hold.release_reason = reason
