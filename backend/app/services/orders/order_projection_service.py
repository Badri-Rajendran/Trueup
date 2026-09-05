"""`OrderProjectionService` (S3 §3.1/§3.2, ADR 7) — folds `order_event` by `seq` into `order`'s
cached `status`/`filled_quantity`/`average_fill_price`.

`fold()` is a pure function deliberately kept independent of any `UnitOfWork` so
`tests/integration`'s property-based suite can call it directly over generated event sequences and
assert `fold(events) == <projection derived from order>` (S3 §8) with no database involved.
`OrderProjectionService` wraps it with the side effects a real event arrival needs: persisting the
new event, rebuilding the whole projection from every event on file (never an incremental "apply
one event onto the existing projection" step, precisely because that would get the wrong answer
under reordering — foundation spec §10 case 4), and releasing the approval hold in the same
transaction the instant the resulting status warrants it (FR-38, S3 §4's last paragraph).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.money import Money, Price, Units
from app.models.orders.approval_hold import ApprovalHoldReleaseReason
from app.models.orders.order import TERMINAL_NON_FILLED_STATUSES, OrderStatus
from app.models.orders.order_event import OrderEventType

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable, Sequence
    from datetime import datetime

    from app.models.orders.order import Order
    from app.models.orders.order_event import OrderEvent
    from app.services.orders.approval_hold_service import ApprovalHoldService
    from app.services.orders.uow import OrdersUnitOfWork

_RELEASE_REASON_BY_TERMINAL_STATUS: dict[OrderStatus, ApprovalHoldReleaseReason] = {
    OrderStatus.REJECTED: ApprovalHoldReleaseReason.REJECTED,
    OrderStatus.CANCELED: ApprovalHoldReleaseReason.CANCELED,
    OrderStatus.EXPIRED: ApprovalHoldReleaseReason.EXPIRED,
}


@dataclass(frozen=True, slots=True)
class OrderProjectionState:
    status: OrderStatus
    filled_quantity: Units
    average_fill_price: Price | None


def fold(events: Sequence[OrderEvent], *, quantity_requested: Units) -> OrderProjectionState:
    """The standing invariant's right-hand side: `assert projection == fold(order_event)` (S3
    §3.1). Sorts by `seq` first, so the result depends only on the events given, never the order
    they were passed in or persisted in (foundation spec §10 case 4)."""
    status = OrderStatus.APPROVED
    filled_quantity = Units("0")
    total_notional = Money("0.00")

    for event in sorted(events, key=lambda e: e.seq):
        if event.event_type is OrderEventType.SUBMITTED:
            status = OrderStatus.SUBMITTED
        elif event.event_type is OrderEventType.ACCEPTED:
            status = OrderStatus.ACCEPTED
        elif event.event_type is OrderEventType.FILL:
            fill_quantity = Units(str(event.payload["quantity"]))
            fill_price = Price(str(event.payload["price"]))
            filled_quantity = filled_quantity + fill_quantity
            total_notional = total_notional + (fill_price * fill_quantity)
            status = (
                OrderStatus.FILLED
                if filled_quantity >= quantity_requested
                else OrderStatus.PARTIALLY_FILLED
            )
        elif event.event_type is OrderEventType.REJECTED:
            status = OrderStatus.REJECTED
        elif event.event_type is OrderEventType.CANCELED:
            status = OrderStatus.CANCELED
        elif event.event_type is OrderEventType.EXPIRED:
            status = OrderStatus.EXPIRED

    average_fill_price = (
        total_notional / filled_quantity if filled_quantity > Units("0") else None
    )
    return OrderProjectionState(
        status=status, filled_quantity=filled_quantity, average_fill_price=average_fill_price
    )


class OrderProjectionService:
    def __init__(
        self,
        uow: OrdersUnitOfWork,
        *,
        hold_service: ApprovalHoldService,
        now: Callable[[], datetime],
    ) -> None:
        self._uow = uow
        self._hold_service = hold_service
        self._now = now

    def apply_new_event(self, order: Order, event: OrderEvent) -> OrderProjectionState:
        """Persist `event`, rebuild `order`'s projection from every event now on file, and
        release the approval hold in the same transaction if the resulting status warrants it.

        Safe to call repeatedly with events that resolve to the same terminal/`submitted` status
        more than once (e.g. a rebuild triggered by a later, unrelated event) --
        `ApprovalHoldService.release` is idempotent (S3 §7 case 5), so this never double-releases
        or errors on an already-released hold.
        """
        self._uow.order_events.add(event)
        self._uow.session.flush()
        events = self._uow.order_events.list_for_order(order.id)
        state = fold(events, quantity_requested=order.quantity_requested)

        order.status = state.status
        order.filled_quantity = state.filled_quantity
        order.average_fill_price = state.average_fill_price

        self._release_hold_if_warranted(order.id, state.status)
        return state

    def _release_hold_if_warranted(self, order_id: uuid.UUID, status: OrderStatus) -> None:
        if status is OrderStatus.SUBMITTED:
            self._hold_service.release(
                order_id,
                ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED,
                released_at=self._now(),
            )
        elif status in TERMINAL_NON_FILLED_STATUSES:
            self._hold_service.release(
                order_id,
                _RELEASE_REASON_BY_TERMINAL_STATUS[status],
                released_at=self._now(),
            )


__all__ = ["OrderProjectionService", "OrderProjectionState", "fold"]
