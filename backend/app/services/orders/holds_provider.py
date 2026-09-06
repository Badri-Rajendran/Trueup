"""The real `CashPolicyService.HoldsProvider` implementation (S1 §5), owned by S3.

Values an unfilled buy's remainder off `average_fill_price` once filled, else the order's
own `approval_hold.amount_money` notional estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.core.money import Money

if TYPE_CHECKING:
    import uuid

    from app.models.orders.approval_hold import ApprovalHoldRepository
    from app.models.orders.order import OrderRepository


class _OrdersAndHoldsUnitOfWork(Protocol):
    """Satisfied by `OrdersUnitOfWork` and by `FundingUnitOfWork`."""

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
