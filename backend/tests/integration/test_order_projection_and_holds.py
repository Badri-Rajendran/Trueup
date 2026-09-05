"""`ApprovalHoldService`/`OrderProjectionService` against real PostgreSQL (S3 §4/§7/§8):
idempotent release (case 5), and the hardest test in §8 -- a terminal event and its hold release
commit or roll back together, never one without the other (FR-38).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.models.orders.approval_hold import (
    ApprovalHold,
    ApprovalHoldReleaseReason,
    ApprovalHoldStatus,
)
from app.models.orders.order import Order, OrderSide, OrderStatus, derive_client_order_id
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.order_projection_service import OrderProjectionService
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer

ORDER_TABLES = [*LEDGER_TABLES, Order.__table__, OrderEvent.__table__, ApprovalHold.__table__]

NOW = datetime(2026, 9, 5, 15, 0, tzinfo=UTC)


@pytest.fixture
def order_tables(owner_engine):
    for table in ORDER_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    for table in reversed(ORDER_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


pytestmark = pytest.mark.usefixtures("order_tables")


def _owner_uow() -> OrdersUnitOfWork:
    return OrdersUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _seed_approved_order_with_hold(customer_id: uuid.UUID, *, quantity: str = "10") -> uuid.UUID:
    with _owner_uow() as uow:
        order_id = uuid.uuid4()
        order = Order(
            id=order_id,
            customer_id=customer_id,
            security_id=uuid.uuid4(),
            side=OrderSide.BUY,
            quantity_requested=Units(quantity),
            status=OrderStatus.APPROVED,
            filled_quantity=Units("0"),
            client_order_id=derive_client_order_id(order_id),
        )
        uow.orders.add(order)
        uow.session.flush()
        ApprovalHoldService(uow).open(
            order_id=order_id, customer_id=customer_id, amount_money=Money("1000.00")
        )
        uow.commit()
    return order_id


def test_release_is_idempotent_for_an_order_with_no_active_hold() -> None:
    """S3 §7 case 5: releasing an already-released or nonexistent hold is a no-op."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        order_id = uuid.uuid4()
        uow.orders.add(
            Order(
                id=order_id,
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity_requested=Units("1"),
                status=OrderStatus.APPROVED,
                filled_quantity=Units("0"),
                client_order_id=derive_client_order_id(order_id),
            )
        )
        uow.commit()

    with _owner_uow() as uow:
        # No hold exists at all (order was below threshold) -- must not raise.
        ApprovalHoldService(uow).release(
            order_id, ApprovalHoldReleaseReason.REJECTED, released_at=NOW
        )
        uow.commit()


def test_release_twice_is_a_no_op_the_second_time() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.commit()
    order_id = _seed_approved_order_with_hold(customer_id)

    with _owner_uow() as uow:
        service = ApprovalHoldService(uow)
        service.release(order_id, ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED, released_at=NOW)
        uow.commit()

    with _owner_uow() as uow:
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        first_released_at = hold.released_at

    with _owner_uow() as uow:
        # Second release, different reason -- idempotent no-op, must not overwrite the first.
        later = datetime(2027, 1, 1, tzinfo=UTC)
        ApprovalHoldService(uow).release(
            order_id, ApprovalHoldReleaseReason.CANCELED, released_at=later
        )
        uow.commit()

    with _owner_uow() as uow:
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert hold is not None
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        assert hold.released_at == first_released_at


def test_active_total_for_customer_sums_only_active_holds() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.commit()
    order_a = _seed_approved_order_with_hold(customer_id, quantity="1")
    order_b = _seed_approved_order_with_hold(customer_id, quantity="2")

    with _owner_uow() as uow:
        ApprovalHoldService(uow).release(
            order_a, ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED, released_at=NOW
        )
        uow.commit()

    with _owner_uow() as uow:
        total = uow.approval_holds.active_total_for_customer(customer_id)

    assert total == Money("1000.00")  # only order_b's hold is still active
    assert order_b  # keep referenced


def test_submitted_event_releases_the_hold_in_the_same_transaction() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.commit()
    order_id = _seed_approved_order_with_hold(customer_id)

    with _owner_uow() as uow:
        order = uow.orders.get_for_update(order_id)
        assert order is not None
        hold_service = ApprovalHoldService(uow)
        projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
        projection.apply_new_event(
            order,
            OrderEvent(
                order_id=order_id,
                seq=1,
                event_type=OrderEventType.SUBMITTED,
                payload={},
                recorded_at=NOW,
            ),
        )
        uow.commit()

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert order is not None and order.status is OrderStatus.SUBMITTED
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED


def test_killing_the_transaction_midway_persists_neither_the_event_nor_the_release() -> None:
    """S3 §8's hardest integration test: a terminal event and its hold release commit or roll
    back together. Simulates a mid-way kill by raising inside the `with` block before `commit()`
    -- `UnitOfWork.__exit__` rolls back on any exception, never a partial commit."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.commit()
    order_id = _seed_approved_order_with_hold(customer_id)

    class _SimulatedKillError(Exception):
        pass

    with pytest.raises(_SimulatedKillError), _owner_uow() as uow:
        order = uow.orders.get_for_update(order_id)
        assert order is not None
        hold_service = ApprovalHoldService(uow)
        projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
        projection.apply_new_event(
            order,
            OrderEvent(
                order_id=order_id,
                seq=1,
                event_type=OrderEventType.CANCELED,
                payload={},
                recorded_at=NOW,
            ),
        )
        raise _SimulatedKillError  # the mid-way kill -- neither write has committed yet

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        events = uow.order_events.list_for_order(order_id)

        assert order is not None
        assert order.status is OrderStatus.APPROVED  # unchanged -- projection update rolled back
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.ACTIVE  # unchanged -- release rolled back
        assert events == []  # the order_event insert itself rolled back too


def test_successful_commit_persists_both_the_event_and_the_release_together() -> None:
    """The positive half of the same guarantee: a real commit persists both."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.commit()
    order_id = _seed_approved_order_with_hold(customer_id)

    with _owner_uow() as uow:
        order = uow.orders.get_for_update(order_id)
        assert order is not None
        hold_service = ApprovalHoldService(uow)
        projection = OrderProjectionService(uow, hold_service=hold_service, now=lambda: NOW)
        projection.apply_new_event(
            order,
            OrderEvent(
                order_id=order_id,
                seq=1,
                event_type=OrderEventType.REJECTED,
                payload={},
                recorded_at=NOW,
            ),
        )
        uow.commit()

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        events = uow.order_events.list_for_order(order_id)

        assert order is not None and order.status is OrderStatus.REJECTED
        assert hold is not None and hold.status is ApprovalHoldStatus.RELEASED
        assert hold.release_reason is ApprovalHoldReleaseReason.REJECTED
        assert len(events) == 1
