"""S9 §9's unit-level tests for `RebalanceOrderService` (S9 §6): sells-before-buys ordering, the
cash-buffer sizing arithmetic, and the buffer-drives-a-buy-to-zero edge case (S9 §8 item 5) -- all
runnable with no database, via the `OrderPlacer`/`InvestableCashProvider` `Protocol`s this module's
own docstring calls out.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Literal

from app.core.money import Money, Price, Units
from app.models.orders.order import Order, OrderSide
from app.services.rebalance.drift_evaluation_service import DriftEntry, DriftEvaluation
from app.services.rebalance.rebalance_order_service import RebalanceOrderService


class _FakeOrderPlacer:
    def __init__(self) -> None:
        self.calls: list[tuple[OrderSide, uuid.UUID, Units]] = []

    def place(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        side: OrderSide,
        quantity: Units,
        reference_price: Price,
    ) -> Order:
        self.calls.append((side, security_id, quantity))
        return Order(
            customer_id=customer_id,
            security_id=security_id,
            side=side,
            quantity_requested=quantity,
            client_order_id=f"test-{security_id}-{side.value}-{len(self.calls)}",
        )


class _FakeCashProvider:
    def __init__(self, investable: Money) -> None:
        self._investable = investable

    def investable(self, customer_id: uuid.UUID) -> Money:
        return self._investable


_DEFAULT_PRICE = Price("100.00")


def _entry(
    *,
    security_id: uuid.UUID | None,
    direction: Literal["buy", "sell"],
    current_value: Money,
    target_value: Money,
    price: Price | None = _DEFAULT_PRICE,
) -> DriftEntry:
    return DriftEntry(
        security_id=security_id,
        current_market_value=current_value,
        target_market_value=target_value,
        current_weight_pct=Decimal("0"),
        target_weight_pct=Decimal("0"),
        price=price,
        is_flagged=True,
        direction=direction,
    )


def _evaluation(entries: list[DriftEntry], *, total_value: Money) -> DriftEvaluation:
    return DriftEvaluation(
        customer_id=uuid.uuid4(),
        model_portfolio_id=uuid.uuid4(),
        as_of_date=date(2026, 9, 5),
        completeness="complete",
        total_value=total_value,
        entries=tuple(entries),
    )


def test_sells_are_placed_before_buys_even_when_a_buy_appears_first_in_the_evaluation() -> None:
    sell_security = uuid.uuid4()
    buy_security = uuid.uuid4()
    evaluation = _evaluation(
        [
            _entry(
                security_id=buy_security,
                direction="buy",
                current_value=Money("0.00"),
                target_value=Money("1000.00"),
            ),
            _entry(
                security_id=sell_security,
                direction="sell",
                current_value=Money("1000.00"),
                target_value=Money("0.00"),
            ),
        ],
        total_value=Money("10000.00"),
    )
    placer = _FakeOrderPlacer()
    service = RebalanceOrderService(
        order_placer=placer,
        cash_provider=_FakeCashProvider(Money("10000.00")),
        cash_buffer_pct=Decimal("0.01"),
    )

    service.generate_orders(evaluation)

    sides_and_securities = [(side, security_id) for side, security_id, _ in placer.calls]
    assert sides_and_securities == [
        (OrderSide.SELL, sell_security),
        (OrderSide.BUY, buy_security),
    ]


def test_the_cash_holding_never_itself_produces_an_order() -> None:
    evaluation = _evaluation(
        [
            _entry(
                security_id=None,
                direction="sell",
                current_value=Money("500.00"),
                target_value=Money("0.00"),
                price=None,
            )
        ],
        total_value=Money("10000.00"),
    )
    placer = _FakeOrderPlacer()
    service = RebalanceOrderService(
        order_placer=placer,
        cash_provider=_FakeCashProvider(Money("10000.00")),
        cash_buffer_pct=Decimal("0.01"),
    )

    orders = service.generate_orders(evaluation)

    assert orders == []
    assert placer.calls == []


def test_buy_notional_is_capped_by_investable_cash_minus_the_buffer() -> None:
    """S9 §5/§6: `available_for_buys = investable(customer) - (portfolio_value * buffer_pct)`,
    and a buy exceeding it is capped to exactly that headroom, not rejected outright."""
    security = uuid.uuid4()
    evaluation = _evaluation(
        [
            _entry(
                security_id=security,
                direction="buy",
                current_value=Money("0.00"),
                target_value=Money("5000.00"),  # wants a full $5000 buy
                price=Price("100.00"),
            )
        ],
        total_value=Money("10000.00"),  # buffer = 1% * 10000 = 100.00
    )
    placer = _FakeOrderPlacer()
    service = RebalanceOrderService(
        order_placer=placer,
        cash_provider=_FakeCashProvider(Money("2100.00")),  # available = 2100 - 100 = 2000.00
        cash_buffer_pct=Decimal("0.01"),
    )

    service.generate_orders(evaluation)

    assert len(placer.calls) == 1
    _, placed_security, quantity = placer.calls[0]
    assert placed_security == security
    assert quantity == Units("20")  # 2000.00 / 100.00 -- capped, not the full 5000.00 / 100.00


def test_the_cash_buffer_consuming_all_headroom_generates_no_buy_orders() -> None:
    """S9 §8 item 5: a buffer constraint reducing a buy's sizing to zero is a valid outcome, not
    an error -- a customer near-fully invested already, with little slack."""
    security = uuid.uuid4()
    evaluation = _evaluation(
        [
            _entry(
                security_id=security,
                direction="buy",
                current_value=Money("0.00"),
                target_value=Money("1000.00"),
                price=Price("100.00"),
            )
        ],
        total_value=Money("10000.00"),  # buffer = 100.00
    )
    placer = _FakeOrderPlacer()
    service = RebalanceOrderService(
        order_placer=placer,
        cash_provider=_FakeCashProvider(Money("100.00")),  # available = 100 - 100 = 0
        cash_buffer_pct=Decimal("0.01"),
    )

    orders = service.generate_orders(evaluation)

    assert orders == []
    assert placer.calls == []


def test_no_flagged_entries_returns_no_orders_and_touches_neither_dependency() -> None:
    evaluation = _evaluation([], total_value=Money("10000.00"))
    placer = _FakeOrderPlacer()

    class _ExplodingCashProvider:
        def investable(self, customer_id: uuid.UUID) -> Money:
            raise AssertionError("investable() should not be called with nothing to buy")

    service = RebalanceOrderService(
        order_placer=placer,
        cash_provider=_ExplodingCashProvider(),
        cash_buffer_pct=Decimal("0.01"),
    )

    assert service.generate_orders(evaluation) == []
    assert placer.calls == []
