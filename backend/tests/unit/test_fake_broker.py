"""`FakeBrokerAdapter`: submission behavior and synthesized message shapes accepted by
`TradeUpdatesConsumer.handle_message`, no websocket opened (S3 §8, ADR 22)."""

from __future__ import annotations

from typing import Any

import pytest

from app.integrations.alpaca.trade_updates_consumer import (
    TradeUpdatesConsumer,
    TrustedTransportVerifier,
)
from app.integrations.fake.fake_broker import BrokerSubmissionRejectedError, FakeBrokerAdapter
from app.integrations.ports import OrderSide
from app.services.intake.event_intake import EventIntakeService, IntakeResult


class _InboundEvents:
    def __init__(self) -> None:
        self.created: list[Any] = []

    def record(self, event: Any) -> None:
        self.created.append(event)


class _Outbox:
    def enqueue(self, task: str, payload: dict[str, str]) -> None:
        return None


class _Uow:
    def __init__(self) -> None:
        self.inbound_events = _InboundEvents()
        self.outbox = _Outbox()

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def notify_outbox_ready(self) -> None:
        return None

    def commit(self) -> None:
        return None


def test_submit_order_records_the_call_and_returns_a_handle() -> None:
    broker = FakeBrokerAdapter()

    handle = broker.submit_order(
        client_order_id="trueup-1", symbol="AAPL", side=OrderSide.BUY, quantity="2.5"
    )

    assert handle.client_order_id == "trueup-1"
    assert broker.submitted_orders == [
        {
            "client_order_id": "trueup-1",
            "broker_order_id": handle.broker_order_id,
            "symbol": "AAPL",
            "side": OrderSide.BUY,
            "quantity": "2.5",
        }
    ]


def test_reject_on_submit_raises_instead_of_returning_a_handle() -> None:
    broker = FakeBrokerAdapter()
    broker.reject_on_submit("trueup-2")

    with pytest.raises(BrokerSubmissionRejectedError):
        broker.submit_order(
            client_order_id="trueup-2", symbol="AAPL", side=OrderSide.SELL, quantity="1"
        )


@pytest.mark.parametrize(
    "builder,event_type",
    [
        (FakeBrokerAdapter.accepted_message, "new"),
        (FakeBrokerAdapter.rejected_message, "rejected"),
        (FakeBrokerAdapter.canceled_message, "canceled"),
        (FakeBrokerAdapter.expired_message, "expired"),
    ],
)
def test_lifecycle_message_shapes_are_accepted_by_the_consumer(
    builder: Any, event_type: str
) -> None:
    uow = _Uow()
    consumer = TradeUpdatesConsumer(
        intake=EventIntakeService(lambda: uow, TrustedTransportVerifier())
    )
    message = builder(broker_order_id="broker-1", client_order_id="trueup-3", symbol="AAPL")

    result = consumer.handle_message(message)

    assert result is IntakeResult.ACCEPTED
    assert uow.inbound_events.created[0].payload["event"] == event_type


def test_fill_message_shape_carries_execution_id_quantity_and_price() -> None:
    uow = _Uow()
    consumer = TradeUpdatesConsumer(
        intake=EventIntakeService(lambda: uow, TrustedTransportVerifier())
    )
    message = FakeBrokerAdapter.fill_message(
        broker_order_id="broker-1",
        client_order_id="trueup-3",
        symbol="AAPL",
        execution_id="exec-9",
        quantity="3.5",
        price="102.10",
    )

    result = consumer.handle_message(message)

    assert result is IntakeResult.ACCEPTED
    assert uow.inbound_events.created[0].source_event_id == "exec-9"
