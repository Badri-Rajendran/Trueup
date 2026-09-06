"""`MarketDataPort` contract (S4 §4): identical assertions against `FakeMarketDataAdapter` and,
when configured, the real `AlpacaMarketDataAdapter`.
"""

from __future__ import annotations

import os
from datetime import date

import pytest

from app.core.money import Price
from app.integrations.fake.fake_market_data import FakeMarketDataAdapter
from app.integrations.ports import CloseQuote, MarketDataPort


def _assert_contract(port: MarketDataPort, *, symbol: str, market_date: date) -> None:
    missing = port.get_close(symbol=symbol, market_date=date(1901, 1, 1))
    assert missing is None  # MarketDataPort's contract: no data yet reports None, never raises.

    quote = port.get_close(symbol=symbol, market_date=market_date)
    assert quote is not None
    assert quote.security_symbol == symbol
    assert quote.market_date == market_date
    assert isinstance(quote.close_price, Price)
    assert quote.close_price > Price("0")


def test_fake_market_data_adapter_satisfies_the_contract() -> None:
    adapter = FakeMarketDataAdapter()
    market_date = date(2026, 9, 2)
    adapter.set_close(
        CloseQuote(security_symbol="AAPL", market_date=market_date, close_price=Price("150.00"))
    )
    _assert_contract(adapter, symbol="AAPL", market_date=market_date)


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY")),
    reason="requires real Alpaca paper credentials (ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY)",
)
def test_real_alpaca_market_data_adapter_satisfies_the_contract() -> None:
    from app.integrations.alpaca.market_data_adapter import AlpacaMarketDataAdapter

    adapter = AlpacaMarketDataAdapter(
        api_key_id=os.environ["ALPACA_API_KEY_ID"],
        api_secret_key=os.environ["ALPACA_API_SECRET_KEY"],
    )
    # A known trading day, settled and stable for CI.
    _assert_contract(adapter, symbol="AAPL", market_date=date(2025, 1, 2))
