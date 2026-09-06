"""`AlpacaMarketDataAdapter` (S4 §4, ADR 12) — `MarketDataPort → Alpaca`. Owns only stock-data-API
calls; the sibling `AlpacaCalendarAdapter` owns the trading-calendar API.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.data.models.bars import BarSet
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from app.core.money import Price
from app.integrations.ports import CloseQuote

if TYPE_CHECKING:
    from datetime import date


class AlpacaMarketDataAdapter:
    """`get_close` reports exactly what Alpaca said — an empty bar set returns `None`, never
    backfilled from an adjacent day."""

    def __init__(self, *, api_key_id: str, api_secret_key: str, sandbox: bool = False) -> None:
        self._client = StockHistoricalDataClient(
            api_key=api_key_id, secret_key=api_secret_key, sandbox=sandbox
        )

    def get_close(self, *, symbol: str, market_date: date) -> CloseQuote | None:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(1, TimeFrameUnit.Day),
            start=datetime.combine(market_date, time.min, tzinfo=UTC),
            end=datetime.combine(market_date, time.max, tzinfo=UTC),
        )
        bar_set = self._client.get_stock_bars(request)
        if not isinstance(bar_set, BarSet):  # pragma: no cover - raw_data=False is never set here
            raise TypeError(f"expected a wrapped BarSet, got {type(bar_set).__name__}")
        bars = bar_set.data.get(symbol, [])
        if not bars:
            return None
        bar = bars[-1]  # at most one bar for the window; last one wins if more than one returned
        return CloseQuote(
            security_symbol=symbol,
            market_date=market_date,
            close_price=Price(Decimal(str(bar.close))),
        )


__all__ = ["AlpacaMarketDataAdapter"]
