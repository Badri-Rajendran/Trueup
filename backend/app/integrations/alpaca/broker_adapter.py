"""`AlpacaBrokerAdapter` (S3 §6, ADR 21) — `BrokerPort → Alpaca Paper Trading`.

`TimeInForce.DAY`: Alpaca requires `day` for fractional-quantity orders (ADR 21/S9 §5 — every
order this system places uses an exact fractional quantity, never rounded to a whole share), so
this is not a tunable choice but the only value Alpaca's own API accepts for the order shapes this
system generates.

Raises `alpaca.common.exceptions.APIError` on a rejected submission or transport failure; never
caught here. `submit_order` runs inside an outbox task handler (S3 §4), and the outbox worker's own
exponential-backoff retry (`app/workers/outbox.py`) is the retry mechanism — an adapter-level retry
here would duplicate it with its own independent backoff clock.
"""

from __future__ import annotations

from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide as AlpacaOrderSide
from alpaca.trading.enums import TimeInForce
from alpaca.trading.models import Order as AlpacaOrder
from alpaca.trading.requests import MarketOrderRequest

from app.integrations.ports import BrokerOrderHandle, OrderSide

_SIDE_TO_ALPACA = {
    OrderSide.BUY: AlpacaOrderSide.BUY,
    OrderSide.SELL: AlpacaOrderSide.SELL,
}


class AlpacaBrokerAdapter:
    def __init__(self, *, api_key_id: str, api_secret_key: str, paper: bool = True) -> None:
        self._client = TradingClient(api_key=api_key_id, secret_key=api_secret_key, paper=paper)

    def submit_order(
        self,
        *,
        client_order_id: str,
        symbol: str,
        side: OrderSide,
        quantity: str,
    ) -> BrokerOrderHandle:
        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=_SIDE_TO_ALPACA[side],
            time_in_force=TimeInForce.DAY,
            client_order_id=client_order_id,
        )
        result = self._client.submit_order(order_data=request)
        if not isinstance(result, AlpacaOrder):
            # Only reachable if `TradingClient` were constructed with `raw_data=True`, which this
            # adapter never does — narrows the SDK's own broader return type for mypy, and fails
            # loudly rather than returning a handle built from an unvalidated dict.
            raise TypeError(f"expected an Alpaca Order, got {type(result).__name__}")
        return BrokerOrderHandle(
            broker_order_id=str(result.id), client_order_id=result.client_order_id
        )


__all__ = ["AlpacaBrokerAdapter"]
