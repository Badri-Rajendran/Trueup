"""`FakeMarketDataAdapter` — an in-memory `MarketDataPort` for the contract suite and unit tests
(`backend/CLAUDE.md`'s four-layer harness: this and `AlpacaMarketDataAdapter` are tested by the
identical contract suite so this fake cannot silently drift from the provider it stands in for)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from app.integrations.ports import CloseQuote


class FakeMarketDataAdapter:
    """Closes are seeded explicitly via `set_close`; an unseeded `(symbol, market_date)` reports
    `None`, matching `MarketDataPort.get_close`'s "the provider has no close yet" contract."""

    def __init__(self) -> None:
        self._closes: dict[tuple[str, date], CloseQuote] = {}

    def set_close(self, quote: CloseQuote) -> None:
        self._closes[(quote.security_symbol, quote.market_date)] = quote

    def get_close(self, *, symbol: str, market_date: date) -> CloseQuote | None:
        return self._closes.get((symbol, market_date))


__all__ = ["FakeMarketDataAdapter"]
