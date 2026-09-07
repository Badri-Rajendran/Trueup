"""`FakeBrokerAdapter` — an in-memory `BrokerPort` for the contract suite and unit tests. Also
emits the same `trade_updates` event shapes Alpaca's websocket would (ADR 22), for testing
`TradeUpdatesConsumer.handle_message` with no live connection.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from app.integrations.ports import BrokerOrderHandle, OrderSide


class BrokerSubmissionRejectedError(RuntimeError):
    """Fake stand-in for `alpaca.common.exceptions.APIError` on a rejected submission, configured
    per `client_order_id` via `reject_on_submit`."""


class FakeBrokerAdapter:
    def __init__(self) -> None:
        self.submitted_orders: list[dict[str, Any]] = []
        self.cancel_requests: list[str] = []
        """`broker_order_id`s passed to `cancel_order`, in call order (ADR 25 test double)."""
        self._reject_client_order_ids: set[str] = set()

    def reject_on_submit(self, client_order_id: str) -> None:
        self._reject_client_order_ids.add(client_order_id)

    def submit_order(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: OrderSide,
        quantity: str,
    ) -> BrokerOrderHandle:
        if client_order_id in self._reject_client_order_ids:
            raise BrokerSubmissionRejectedError(client_order_id)
        broker_order_id = f"fake-broker-order-{uuid.uuid4()}"
        self.submitted_orders.append(
            {
                "client_order_id": client_order_id,
                "broker_order_id": broker_order_id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
            }
        )
        return BrokerOrderHandle(broker_order_id=broker_order_id, client_order_id=client_order_id)

    def cancel_order(self, *, broker_order_id: str) -> None:
        """Records the request; ADR 25 -- never itself produces a `canceled` trade-update.
        Call `canceled_message(...)` and feed it through `AlpacaTradeUpdateHandler` to simulate
        the broker's confirmation."""
        self.cancel_requests.append(broker_order_id)

    @staticmethod
    def _base_message(
        *, event: str, broker_order_id: str, client_order_id: str, symbol: str
    ) -> dict[str, Any]:
        return {
            "event": event,
            "execution_id": None,
            "order": {"id": broker_order_id, "client_order_id": client_order_id, "symbol": symbol},
            "timestamp": datetime.now(UTC).isoformat(),
            "price": None,
            "qty": None,
        }

    @classmethod
    def accepted_message(
        cls, *, broker_order_id: str, client_order_id: str, symbol: str
    ) -> dict[str, Any]:
        return cls._base_message(
            event="new",
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
        )

    @classmethod
    def fill_message(
        cls,
        *,
        broker_order_id: str,
        client_order_id: str,
        symbol: str,
        execution_id: str,
        quantity: str,
        price: str,
    ) -> dict[str, Any]:
        message = cls._base_message(
            event="fill",
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
        )
        message["execution_id"] = execution_id
        message["qty"] = quantity
        message["price"] = price
        return message

    @classmethod
    def rejected_message(
        cls, *, broker_order_id: str, client_order_id: str, symbol: str
    ) -> dict[str, Any]:
        return cls._base_message(
            event="rejected",
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
        )

    @classmethod
    def canceled_message(
        cls, *, broker_order_id: str, client_order_id: str, symbol: str
    ) -> dict[str, Any]:
        return cls._base_message(
            event="canceled",
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
        )

    @classmethod
    def expired_message(
        cls, *, broker_order_id: str, client_order_id: str, symbol: str
    ) -> dict[str, Any]:
        return cls._base_message(
            event="expired",
            broker_order_id=broker_order_id,
            client_order_id=client_order_id,
            symbol=symbol,
        )


__all__ = ["BrokerSubmissionRejectedError", "FakeBrokerAdapter"]
