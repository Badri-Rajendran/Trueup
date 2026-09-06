"""`OrderService` (S3 §4/§6/§7) against real PostgreSQL: the approval-threshold boundary (case 6),
the customer-approval transition, broker submission (with a fake `BrokerPort`), and case 2's
re-check-before-submission gate."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.core.db import DbRole
from app.core.money import Money, Price, Units
from app.core.uow import SessionRole
from app.integrations.fake.fake_broker import FakeBrokerAdapter
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.orders.approval_hold import ApprovalHold, ApprovalHoldStatus
from app.models.orders.order import Order, OrderSide, OrderStatus
from app.models.orders.order_event import OrderEvent
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.order_service import (
    CustomerNotEligibleError,
    InvalidOrderTransitionError,
    OrderCreationRequest,
    OrderNotFoundError,
    OrderService,
)
from app.services.orders.uow import OrdersUnitOfWork
from tests.integration.conftest import LEDGER_TABLES

ORDER_TABLES = [*LEDGER_TABLES, Order.__table__, OrderEvent.__table__, ApprovalHold.__table__]

NOW = datetime(2026, 9, 5, 17, 0, tzinfo=UTC)
THRESHOLD = Money("10000.00")


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


def _insert_eligible_customer(
    uow: OrdersUnitOfWork,
    *,
    kyc_status: KycStatus = KycStatus.approved,
    account_approval_status: AccountApprovalStatus = AccountApprovalStatus.approved,
) -> uuid.UUID:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=kyc_status,
        account_approval_status=account_approval_status,
    )
    uow.session.add(customer)
    uow.session.flush()
    uow.cash_locks.create_for_customer(customer.id)
    return customer.id


def _service(uow: OrdersUnitOfWork) -> OrderService:
    return OrderService(
        uow,
        hold_service=ApprovalHoldService(uow),
        approval_threshold_usd=THRESHOLD,
        now=lambda: NOW,
    )


def test_order_at_or_below_threshold_is_approved_immediately_with_a_hold() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("100"),
                reference_price=Price("100.00"),  # notional = $10,000.00, exactly at threshold
            )
        )
        uow.commit()
        order_id = order.id

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert order is not None and order.status is OrderStatus.APPROVED
        assert hold is not None
        assert hold.status is ApprovalHoldStatus.ACTIVE
        assert hold.amount_money == Money("10000.00")


def test_order_strictly_above_threshold_requires_approval() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("100"),
                reference_price=Price("100.01"),  # notional = $10,001.00, one cent over
            )
        )
        uow.commit()
        order_id = order.id

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        assert order is not None and order.status is OrderStatus.AWAITING_APPROVAL


def test_create_order_rejects_a_customer_who_is_not_kyc_approved() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow, kyc_status=KycStatus.pending)
        with pytest.raises(CustomerNotEligibleError):
            _service(uow).create_order(
                OrderCreationRequest(
                    customer_id=customer_id,
                    security_id=uuid.uuid4(),
                    side=OrderSide.BUY,
                    quantity=Units("1"),
                    reference_price=Price("10"),
                )
            )


def test_approve_transitions_awaiting_approval_to_approved() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("1000"),
                reference_price=Price("100.00"),  # well above threshold
            )
        )
        uow.commit()
        order_id = order.id

    with _owner_uow() as uow:
        approved = _service(uow).approve(order_id)
        assert approved.status is OrderStatus.APPROVED
        uow.commit()

    with _owner_uow() as uow:
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert hold is not None and hold.status is ApprovalHoldStatus.ACTIVE  # unchanged


def test_approve_rejects_an_order_not_awaiting_approval() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("1"),
                reference_price=Price("1.00"),  # below threshold -- already approved
            )
        )
        uow.commit()
        order_id = order.id

    with _owner_uow() as uow, pytest.raises(InvalidOrderTransitionError):
        _service(uow).approve(order_id)


def test_approve_unknown_order_raises_not_found() -> None:
    with _owner_uow() as uow, pytest.raises(OrderNotFoundError):
        _service(uow).approve(uuid.uuid4())


def test_submit_to_broker_fires_submitted_and_releases_the_hold() -> None:
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("1"),
                reference_price=Price("1.00"),
            )
        )
        uow.commit()
        order_id = order.id

    broker = FakeBrokerAdapter()
    with _owner_uow() as uow:
        _service(uow).submit_to_broker(order_id, symbol="AAPL", broker=broker)
        uow.commit()

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert order is not None and order.status is OrderStatus.SUBMITTED
        assert hold is not None and hold.status is ApprovalHoldStatus.RELEASED
        client_order_id = order.client_order_id

    assert broker.submitted_orders[0]["client_order_id"] == client_order_id


def test_submit_to_broker_rejects_and_releases_the_hold_if_the_gate_closed_meanwhile() -> None:
    """S3 §7 case 2: approved but the account is suspended before submission."""
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("1"),
                reference_price=Price("1.00"),
            )
        )
        uow.commit()
        order_id = order.id

    with _owner_uow() as uow:
        customer = uow.customers.get_by_id(customer_id)
        assert customer is not None
        customer.account_approval_status = AccountApprovalStatus.rejected
        uow.commit()

    broker = FakeBrokerAdapter()
    with _owner_uow() as uow:
        _service(uow).submit_to_broker(order_id, symbol="AAPL", broker=broker)
        uow.commit()

    with _owner_uow() as uow:
        order = uow.orders.get_by_id(order_id)
        hold = uow.approval_holds.get_by_order_id(order_id)
        assert order is not None and order.status is OrderStatus.REJECTED
        assert hold is not None and hold.status is ApprovalHoldStatus.RELEASED

    assert broker.submitted_orders == []  # the broker was never called


def test_submit_to_broker_is_a_no_op_for_an_order_not_in_approved_status() -> None:
    """A retried outbox attempt after the order already advanced -- must not double-submit."""
    with _owner_uow() as uow:
        customer_id = _insert_eligible_customer(uow)
        order = _service(uow).create_order(
            OrderCreationRequest(
                customer_id=customer_id,
                security_id=uuid.uuid4(),
                side=OrderSide.BUY,
                quantity=Units("1"),
                reference_price=Price("1.00"),
            )
        )
        uow.commit()
        order_id = order.id

    broker = FakeBrokerAdapter()
    with _owner_uow() as uow:
        _service(uow).submit_to_broker(order_id, symbol="AAPL", broker=broker)
        uow.commit()

    with _owner_uow() as uow:
        _service(uow).submit_to_broker(order_id, symbol="AAPL", broker=broker)
        uow.commit()

    assert len(broker.submitted_orders) == 1  # not called twice
