"""`AlpacaBrokerAdapter` (S3 §6, ADR 21) — `BrokerPort → Alpaca Paper Trading`.

`TimeInForce.DAY` is the only value Alpaca accepts for fractional-quantity orders (ADR 21/S9 §5).
Raises `alpaca.common.exceptions.APIError` uncaught; the outbox worker's own retry is the retry
mechanism, never an adapter-level one.
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
            # Only reachable with raw_data=True, which this adapter never sets.
            raise TypeError(f"expected an Alpaca Order, got {type(result).__name__}")
        return BrokerOrderHandle(
            broker_order_id=str(result.id), client_order_id=result.client_order_id
        )


__all__ = ["AlpacaBrokerAdapter"]
