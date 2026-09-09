"""`LotDesignationService.validate` (FR-20/ADR-4) -- pure validation logic against fake, in-memory
`tax_lots`/`orders` repositories, no database (mirrors `test_rebalance_order_service.py`'s
duck-typed-uow style)."""

from __future__ import annotations

import uuid

import pytest

from app.core.money import Units
from app.models.ledger.tax_lot import TaxLot
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.services.lots.lot_consumption_service import UnknownTaxLotError
from app.services.orders.lot_designation_service import (
    DuplicateLotDesignationError,
    EmptyLotDesignationError,
    InsufficientDesignatedLotsError,
    LotDesignationNotAllowedForBuyError,
    LotDesignationService,
    TooManyDesignatedLotsError,
)

CUSTOMER_ID = uuid.uuid4()
OTHER_CUSTOMER_ID = uuid.uuid4()
SECURITY_ID = uuid.uuid4()
OTHER_SECURITY_ID = uuid.uuid4()


class _FakeTaxLotRepo:
    def __init__(self, lots: list[TaxLot]) -> None:
        self._lots = {lot.id: lot for lot in lots}

    def lock_by_ids(self, lot_ids: list[uuid.UUID]) -> dict[uuid.UUID, TaxLot]:
        return {lot_id: self._lots[lot_id] for lot_id in lot_ids if lot_id in self._lots}


class _FakeOrderRepo:
    def __init__(self, open_sell_orders: list[Order]) -> None:
        self._open_sell_orders = open_sell_orders

    def open_sell_orders(self, customer_id: uuid.UUID) -> list[Order]:
        return [o for o in self._open_sell_orders if o.customer_id == customer_id]


class _FakeUow:
    def __init__(
        self, *, lots: list[TaxLot] | None = None, open_sell_orders: list[Order] | None = None
    ) -> None:
        self.tax_lots = _FakeTaxLotRepo(lots or [])
        self.orders = _FakeOrderRepo(open_sell_orders or [])


def _lot(*, quantity_remaining: str, customer_id: uuid.UUID = CUSTOMER_ID,
          security_id: uuid.UUID = SECURITY_ID) -> TaxLot:
    return TaxLot(
        id=uuid.uuid4(),
        customer_id=customer_id,
        security_id=security_id,
        quantity_remaining=Units(quantity_remaining),
    )


def _open_sell(
    *, designated_lot_ids: list[uuid.UUID] | None, quantity_requested: str, filled_quantity: str,
    customer_id: uuid.UUID = CUSTOMER_ID, status: OrderStatus = OrderStatus.SUBMITTED,
) -> Order:
    order_id = uuid.uuid4()
    return Order(
        id=order_id,
        customer_id=customer_id,
        security_id=SECURITY_ID,
        side=OrderSide.SELL,
        quantity_requested=Units(quantity_requested),
        filled_quantity=Units(filled_quantity),
        status=status,
        designated_lot_ids=designated_lot_ids,
        client_order_id=derive_client_order_id(order_id),
    )


def _service(uow: _FakeUow) -> LotDesignationService:
    return LotDesignationService(uow)  # type: ignore[arg-type]


# --- rule 0: omitted lot_ids means FIFO, unchanged -------------------------------------------


def test_omitted_lot_ids_returns_none_unchanged() -> None:
    service = _service(_FakeUow())

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("5"), lot_ids=None,
    )

    assert result is None


# --- rule 1: buy orders may never designate lots ----------------------------------------------


def test_lot_ids_on_a_buy_order_is_rejected() -> None:
    lot = _lot(quantity_remaining="10")
    service = _service(_FakeUow(lots=[lot]))

    with pytest.raises(LotDesignationNotAllowedForBuyError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.BUY,
            quantity=Units("5"), lot_ids=[lot.id],
        )


# --- rule 2: an explicit empty list is a client bug --------------------------------------------


def test_empty_lot_ids_list_is_rejected() -> None:
    service = _service(_FakeUow())

    with pytest.raises(EmptyLotDesignationError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[],
        )


# --- rule 3: duplicates -------------------------------------------------------------------------


def test_duplicate_lot_ids_are_rejected() -> None:
    lot = _lot(quantity_remaining="10")
    service = _service(_FakeUow(lots=[lot]))

    with pytest.raises(DuplicateLotDesignationError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[lot.id, lot.id],
        )


# --- rule 4: too many lots (OWASP API4) ---------------------------------------------------------


def test_more_than_fifty_lot_ids_is_rejected() -> None:
    service = _service(_FakeUow())
    lot_ids = [uuid.uuid4() for _ in range(51)]

    with pytest.raises(TooManyDesignatedLotsError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=lot_ids,
        )


# --- rule 5: ownership ---------------------------------------------------------------------------


def test_nonexistent_lot_id_is_rejected() -> None:
    service = _service(_FakeUow())

    with pytest.raises(UnknownTaxLotError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[uuid.uuid4()],
        )


def test_lot_belonging_to_another_customer_is_rejected() -> None:
    others_lot = _lot(quantity_remaining="10", customer_id=OTHER_CUSTOMER_ID)
    service = _service(_FakeUow(lots=[others_lot]))

    with pytest.raises(UnknownTaxLotError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[others_lot.id],
        )


def test_lot_belonging_to_another_security_is_rejected() -> None:
    wrong_security_lot = _lot(quantity_remaining="10", security_id=OTHER_SECURITY_ID)
    service = _service(_FakeUow(lots=[wrong_security_lot]))

    with pytest.raises(UnknownTaxLotError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[wrong_security_lot.id],
        )


# --- rule 6: coverage, including the exact-boundary case ----------------------------------------


def test_named_lots_covering_less_than_quantity_is_rejected() -> None:
    lot = _lot(quantity_remaining="5")
    service = _service(_FakeUow(lots=[lot]))

    with pytest.raises(InsufficientDesignatedLotsError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5.000001"), lot_ids=[lot.id],
        )


def test_named_lots_exactly_covering_quantity_is_not_a_false_negative() -> None:
    """The boundary: combined quantity_remaining == requested quantity must pass."""
    lot = _lot(quantity_remaining="5")
    service = _service(_FakeUow(lots=[lot]))

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("5"), lot_ids=[lot.id],
    )

    assert result == [lot.id]


def test_named_lots_covering_more_than_quantity_across_multiple_lots_succeeds() -> None:
    lot_a = _lot(quantity_remaining="3")
    lot_b = _lot(quantity_remaining="4")
    service = _service(_FakeUow(lots=[lot_a, lot_b]))

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("6"), lot_ids=[lot_a.id, lot_b.id],
    )

    assert result == [lot_a.id, lot_b.id]


# --- rule 6: netting against other open sell orders (the double-claim case) --------------------


def test_second_sell_order_naming_an_already_claimed_lot_is_rejected() -> None:
    """Two sell orders name an overlapping lot; the second is rejected once the first has already
    claimed enough of it that nothing remains to cover the second."""
    lot = _lot(quantity_remaining="10")
    first_sell = _open_sell(
        designated_lot_ids=[lot.id], quantity_requested="10", filled_quantity="0",
    )
    service = _service(_FakeUow(lots=[lot], open_sell_orders=[first_sell]))

    with pytest.raises(InsufficientDesignatedLotsError):
        service.validate(
            customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
            quantity=Units("5"), lot_ids=[lot.id],
        )


def test_second_sell_order_naming_a_partially_claimed_lot_succeeds_for_the_remainder() -> None:
    """The first open sell order has only partially claimed the lot's quantity (already filled
    some of it) -- the second can still validate against what's left."""
    lot = _lot(quantity_remaining="10")
    first_sell = _open_sell(
        designated_lot_ids=[lot.id], quantity_requested="10", filled_quantity="4",
    )
    service = _service(_FakeUow(lots=[lot], open_sell_orders=[first_sell]))

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("4"), lot_ids=[lot.id],
    )

    assert result == [lot.id]


def test_open_sell_order_naming_a_disjoint_lot_does_not_affect_netting() -> None:
    lot = _lot(quantity_remaining="10")
    other_lot = _lot(quantity_remaining="10")
    unrelated_sell = _open_sell(
        designated_lot_ids=[other_lot.id], quantity_requested="10", filled_quantity="0",
    )
    service = _service(_FakeUow(lots=[lot], open_sell_orders=[unrelated_sell]))

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("10"), lot_ids=[lot.id],
    )

    assert result == [lot.id]


def test_a_fifo_open_sell_order_with_no_designation_does_not_affect_netting() -> None:
    lot = _lot(quantity_remaining="10")
    fifo_sell = _open_sell(
        designated_lot_ids=None, quantity_requested="10", filled_quantity="0",
    )
    service = _service(_FakeUow(lots=[lot], open_sell_orders=[fifo_sell]))

    result = service.validate(
        customer_id=CUSTOMER_ID, security_id=SECURITY_ID, side=OrderSide.SELL,
        quantity=Units("10"), lot_ids=[lot.id],
    )

    assert result == [lot.id]
