"""`OrderProjectionService.fold` (S3 §3.1/§8) — the standing `projection == fold(order_event)`
invariant, exercised as a pure function with no database involved.
"""

from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from app.core.money import Price, Units
from app.models.orders.order import OrderStatus
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.orders.order_projection_service import fold


def _event(
    *, seq: int, event_type: OrderEventType, payload: dict[str, object] | None = None
) -> OrderEvent:
    return OrderEvent(
        id=uuid.uuid4(),
        order_id=uuid.uuid4(),
        seq=seq,
        event_type=event_type,
        execution_id=f"exec-{seq}" if event_type is OrderEventType.FILL else None,
        payload=payload or {},
        recorded_at=datetime.now(UTC),
    )


def test_fold_full_fill_computes_weighted_average_price() -> None:
    events = [
        _event(seq=1, event_type=OrderEventType.SUBMITTED),
        _event(seq=2, event_type=OrderEventType.ACCEPTED),
        _event(seq=3, event_type=OrderEventType.FILL, payload={"quantity": "5", "price": "100"}),
        _event(seq=4, event_type=OrderEventType.FILL, payload={"quantity": "5", "price": "102"}),
    ]

    state = fold(events, quantity_requested=Units("10"))

    assert state.status is OrderStatus.FILLED
    assert state.filled_quantity == Units("10")
    assert state.average_fill_price == Price("101")


def test_fold_partial_fill_stays_partially_filled() -> None:
    events = [
        _event(seq=1, event_type=OrderEventType.SUBMITTED),
        _event(seq=2, event_type=OrderEventType.ACCEPTED),
        _event(seq=3, event_type=OrderEventType.FILL, payload={"quantity": "4", "price": "50"}),
    ]

    state = fold(events, quantity_requested=Units("10"))

    assert state.status is OrderStatus.PARTIALLY_FILLED
    assert state.filled_quantity == Units("4")
    assert state.average_fill_price == Price("50")


def test_fold_terminal_with_no_fill_has_no_average_price() -> None:
    events = [
        _event(seq=1, event_type=OrderEventType.SUBMITTED),
        _event(seq=2, event_type=OrderEventType.REJECTED),
    ]

    state = fold(events, quantity_requested=Units("10"))

    assert state.status is OrderStatus.REJECTED
    assert state.filled_quantity == Units("0")
    assert state.average_fill_price is None


def test_fold_out_of_order_arrival_of_fill_before_accepted() -> None:
    """Foundation spec §10 case 4: a fill can arrive before its order's accepted event."""
    submitted = _event(seq=1, event_type=OrderEventType.SUBMITTED)
    accepted = _event(seq=2, event_type=OrderEventType.ACCEPTED)
    fill = _event(seq=3, event_type=OrderEventType.FILL, payload={"quantity": "10", "price": "20"})

    # Handed to fold() in arrival order (fill before accepted) -- seq still says accepted first.
    state = fold([submitted, fill, accepted], quantity_requested=Units("10"))

    assert state.status is OrderStatus.FILLED
    assert state.filled_quantity == Units("10")


@given(
    fill_quantities=st.lists(
        st.integers(min_value=1, max_value=5).map(str), min_size=0, max_size=4
    ),
    terminal=st.sampled_from(
        [None, OrderEventType.CANCELED, OrderEventType.EXPIRED, OrderEventType.REJECTED]
    ),
    seed=st.integers(min_value=0, max_value=2**32 - 1),
)
def test_fold_is_independent_of_list_order_given_fixed_seq(
    fill_quantities: list[str], terminal: OrderEventType | None, seed: int
) -> None:
    """The projection depends only on `seq`, never on the order events are handed to `fold()` in
    (S3 §8's property-based requirement, foundation spec §10 case 4)."""
    quantity_requested = Units("100")
    canonical: list[OrderEvent] = [
        _event(seq=0, event_type=OrderEventType.SUBMITTED),
        _event(seq=1, event_type=OrderEventType.ACCEPTED),
    ]
    for i, quantity in enumerate(fill_quantities, start=2):
        canonical.append(
            _event(
                seq=i,
                event_type=OrderEventType.FILL,
                payload={"quantity": quantity, "price": "10"},
            )
        )
    if terminal is not None:
        canonical.append(_event(seq=len(canonical), event_type=terminal))

    shuffled = list(canonical)
    random.Random(seed).shuffle(shuffled)

    expected = fold(canonical, quantity_requested=quantity_requested)
    actual = fold(shuffled, quantity_requested=quantity_requested)

    assert actual == expected
