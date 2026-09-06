"""`TradeUpdatesConsumer.handle_message`: pure, no websocket opened (S3 §6, ADR 22)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.integrations.alpaca.trade_updates_consumer import (
    AlpacaTradeUpdateMessage,
    TradeUpdatesConsumer,
    TrustedTransportVerifier,
    source_event_id_for,
)
from app.models.ops.inbound_event import InboundEventSource
from app.services.intake.event_intake import EventIntakeService, IntakeResult


class _InboundEvents:
    def __init__(self) -> None:
        self.created: list[Any] = []

    def record(self, event: Any) -> None:
        self.created.append(event)


class _Outbox:
    def __init__(self) -> None:
        self.enqueued: list[Any] = []

    def enqueue(self, task: str, payload: dict[str, str]) -> None:
        self.enqueued.append((task, payload))


class _Uow:
    def __init__(self) -> None:
        self.inbound_events = _InboundEvents()
        self.outbox = _Outbox()
        self.committed = False

    def __enter__(self) -> _Uow:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def notify_outbox_ready(self) -> None:
        return None

    def commit(self) -> None:
        self.committed = True


def _consumer(uow: _Uow) -> TradeUpdatesConsumer:
    intake = EventIntakeService(lambda: uow, TrustedTransportVerifier())
    return TradeUpdatesConsumer(intake=intake)


def _fill_message(**overrides: Any) -> dict[str, Any]:
    message = {
        "event": "fill",
        "execution_id": "exec-1",
        "order": {"id": "broker-order-1", "client_order_id": "trueup-abc", "symbol": "AAPL"},
        "timestamp": "2026-09-05T14:30:00Z",
        "price": "101.230000",
        "qty": "5.000000",
    }
    message.update(overrides)
    return message


def test_fill_event_is_intaken_keyed_on_execution_id() -> None:
    uow = _Uow()
    result = _consumer(uow).handle_message(_fill_message())

    assert result is IntakeResult.ACCEPTED
    assert uow.inbound_events.created[0].source is InboundEventSource.ALPACA
    assert uow.inbound_events.created[0].source_event_id == "exec-1"
    assert uow.inbound_events.created[0].signature_verified is True


def test_source_event_id_for_non_fill_events_is_deterministic_with_no_execution_id() -> None:
    """A redelivered byte-identical message must dedupe like a redelivered fill (ADR 7/22)."""
    message = AlpacaTradeUpdateMessage.model_validate(
        _fill_message(event="canceled", execution_id=None)
    )

    first = source_event_id_for(message)
    second = source_event_id_for(AlpacaTradeUpdateMessage.model_validate(message.model_dump()))
    expected_epoch = datetime(2026, 9, 5, 14, 30, tzinfo=UTC).timestamp()

    assert first == second
    assert first == f"broker-order-1:canceled:{expected_epoch}"


def test_canceled_event_with_no_execution_id_is_still_intaken() -> None:
    uow = _Uow()
    result = _consumer(uow).handle_message(_fill_message(event="canceled", execution_id=None))

    assert result is IntakeResult.ACCEPTED
    assert uow.inbound_events.created[0].source_event_id == (
        f"broker-order-1:canceled:{datetime(2026, 9, 5, 14, 30, tzinfo=UTC).timestamp()}"
    )


@pytest.mark.parametrize("alpaca_event", ["pending_new", "replaced", "restated", "pending_cancel"])
def test_untracked_alpaca_events_are_ignored_not_inserted(alpaca_event: str) -> None:
    uow = _Uow()
    result = _consumer(uow).handle_message(_fill_message(event=alpaca_event, execution_id=None))

    assert result is None
    assert uow.inbound_events.created == []


def test_malformed_payload_fails_pydantic_validation_before_any_service_sees_it() -> None:
    uow = _Uow()
    with pytest.raises(ValidationError):
        _consumer(uow).handle_message({"event": "fill"})  # missing order/timestamp

    assert uow.inbound_events.created == []
