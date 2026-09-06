"""`OrderHoldsProvider` — the real `CashPolicyService.HoldsProvider` (S1 §5) S3 owns implementing.

Replaces `app.services.identity.null_holds_provider.NullHoldsProvider` at its wiring point
(`app/controllers/api/funding.py`) — funding-engineer's stand-in, not this module's to swap in,
since that controller is outside this sub-project's file set.

`open_buy_commitments`'s valuation of a still-open buy order's *unfilled* remainder is a judgment
call worth a second look: once a fill exists, `average_fill_price` is a real execution price and
values the remainder off it; before any fill, the order carries no price of its own (S3 §3.1's
schema has none), so this falls back to the order's own `approval_hold.amount_money` — the
notional estimate computed at order-creation time, still on that row even after release
(`approval_hold` is not append-only; a released row is simply no longer `active`, never deleted).
Reusing it here means an unfilled order is never valued at zero while it is genuinely committing a
customer's cash to a pending buy, without inventing a new persisted column this design doesn't
already have.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.core.money import Money

if TYPE_CHECKING:
    import uuid

    from app.models.orders.approval_hold import ApprovalHoldRepository
    from app.models.orders.order import OrderRepository


class _OrdersAndHoldsUnitOfWork(Protocol):
    """The minimal structural surface `OrderHoldsProvider` needs -- `OrdersUnitOfWork` satisfies
    it, and so does `FundingUnitOfWork` (`app/controllers/api/funding.py`'s own wiring point, per
    this module's original docstring) once it exposes the same two repositories. A concrete
    `OrdersUnitOfWork` annotation here would force `funding.py` onto a UnitOfWork built for a
    different sub-project's whole transaction shape just to reuse two repository accessors."""

    @property
    def orders(self) -> OrderRepository: ...

    @property
    def approval_holds(self) -> ApprovalHoldRepository: ...


class OrderHoldsProvider:
    def __init__(self, uow: _OrdersAndHoldsUnitOfWork) -> None:
        self._uow = uow

    def holds(self, customer_id: uuid.UUID) -> Money:
        return self._uow.approval_holds.active_total_for_customer(customer_id)

    def open_buy_commitments(self, customer_id: uuid.UUID) -> Money:
        total = Money("0.00")
        for order in self._uow.orders.open_buy_orders(customer_id):
            remaining = order.quantity_requested - order.filled_quantity
            if order.average_fill_price is not None:
                total += remaining * order.average_fill_price
                continue
            hold = self._uow.approval_holds.get_by_order_id(order.id)
            if hold is not None:
                total += hold.amount_money
        return total


__all__ = ["OrderHoldsProvider"]
