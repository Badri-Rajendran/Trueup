"""Validates a customer's specific-ID lot designation at order-placement time (FR-20, ADR 4).

The consumption-time domain logic (`LotConsumptionService.record_sell_fill`) already validates
ownership and consumes exactly the named lots; this service only decides whether a designation is
even admissible to *place* -- side, shape, and whether the named lots (net of what other open sell
orders have already claimed) can actually cover the requested quantity. There is no FIFO fallback
here for an uncovered remainder: an explicit designation determines the customer's realized
gain/loss, so a shortfall is always rejected, never silently substituted.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.money import Units
from app.models.orders.order import OrderSide
from app.services.lots.lot_consumption_service import UnknownTaxLotError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from app.services.orders.uow import OrdersUnitOfWork

_MAX_DESIGNATED_LOTS = 50
"""OWASP API4 (unbounded resource consumption): checked before any DB round-trip."""


class LotDesignationNotAllowedForBuyError(RuntimeError):
    """`lot_ids` was supplied for a buy order; specific-ID designation only applies to sells."""


class EmptyLotDesignationError(RuntimeError):
    """`lot_ids` was an explicit empty list -- a client bug, distinct from omitting the field
    (which means FIFO)."""


class DuplicateLotDesignationError(RuntimeError):
    """`lot_ids` named the same tax lot more than once."""


class TooManyDesignatedLotsError(RuntimeError):
    """`lot_ids` exceeded the per-order cap."""


class InsufficientDesignatedLotsError(RuntimeError):
    """The named lots, net of what other open sell orders have already claimed from them, cannot
    cover the requested quantity. No FIFO fallback: the order is rejected outright."""


class LotDesignationService:
    def __init__(self, uow: OrdersUnitOfWork) -> None:
        self._uow = uow

    def validate(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        side: OrderSide,
        quantity: Units,
        lot_ids: Sequence[uuid.UUID] | None,
    ) -> list[uuid.UUID] | None:
        """Returns the validated designation to store on `Order.designated_lot_ids`, or `None`
        unchanged when the caller omitted one (FIFO)."""
        if lot_ids is None:
            return None
        if side is not OrderSide.SELL:
            raise LotDesignationNotAllowedForBuyError(
                "lot_ids may only be designated on a sell order"
            )
        if len(lot_ids) == 0:
            raise EmptyLotDesignationError(
                "lot_ids was an explicit empty list; omit the field for FIFO"
            )
        if len(set(lot_ids)) != len(lot_ids):
            raise DuplicateLotDesignationError("lot_ids contains a duplicate tax lot id")
        if len(lot_ids) > _MAX_DESIGNATED_LOTS:
            raise TooManyDesignatedLotsError(
                f"lot_ids named {len(lot_ids)} lots, more than the {_MAX_DESIGNATED_LOTS} allowed"
            )

        locked = self._uow.tax_lots.lock_by_ids(lot_ids)
        named_lots = []
        for lot_id in lot_ids:
            lot = locked.get(lot_id)
            if lot is None or lot.customer_id != customer_id or lot.security_id != security_id:
                raise UnknownTaxLotError(
                    f"no tax lot found for id={lot_id!r} belonging to customer {customer_id!r} "
                    f"/ security {security_id!r}"
                )
            named_lots.append(lot)

        named_total = Units("0")
        for lot in named_lots:
            named_total = named_total + lot.quantity_remaining

        named_ids = set(lot_ids)
        already_committed = Units("0")
        for open_sell in self._uow.orders.open_sell_orders(customer_id):
            open_designation = open_sell.designated_lot_ids
            if open_designation and named_ids.intersection(open_designation):
                already_committed = already_committed + (
                    open_sell.quantity_requested - open_sell.filled_quantity
                )

        if named_total - already_committed < quantity:
            raise InsufficientDesignatedLotsError(
                f"named lots cover {named_total - already_committed} after netting against other "
                f"open sell orders, less than the requested {quantity}"
            )

        return list(lot_ids)


__all__ = [
    "DuplicateLotDesignationError",
    "EmptyLotDesignationError",
    "InsufficientDesignatedLotsError",
    "LotDesignationNotAllowedForBuyError",
    "LotDesignationService",
    "TooManyDesignatedLotsError",
]
