"""`CachedTradingCalendar` — the `TradingCalendar` (`app/core/clock.py`) implementation that reads
`market_calendar_cache` (S4 §3.4), so `MarketClock` can convert UTC instants to market days without
`app/core/` ever importing a model (ADR 12, S0 §3's layering constraint).

Placed in the model layer, not services: this class has no business logic beyond the query itself
and the honest-degradation rule below -- the same weight class as `BaseRepository` itself, one layer
below where `ValuationService`/`TwrService` live.

**A cache miss raises, it never silently reads as a holiday.** `TradingCalendar.is_trading_day()`
and `session_close()` are declared to return a plain `bool`/`datetime | None` with no error channel,
but S4 §3.4 is explicit that an absent cache row is an operational condition ("the calendar has
not been fetched for that date"), not evidence of a holiday -- collapsing the two would silently
suppress exactly the missed-valuation alert §6 and S0 §10.7 exist to raise.
`MarketCalendarCacheMissError` is that operational condition surfacing as loudly as the Protocol's
shape allows: raised rather than returned, so a caller cannot accidentally treat it as `False`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from app.models.marketdata.market_calendar_cache import MarketCalendarCacheRepository


class MarketCalendarCacheMissError(RuntimeError):
    """`market_calendar_cache` has no row for this date yet (S4 §3.4) — the calendar has not been
    fetched, which is distinct from (and must never be conflated with) a fetched holiday."""


class CachedTradingCalendar:
    """Satisfies `app.core.clock.TradingCalendar` by querying `market_calendar_cache` through the
    injected repository. `CalendarPort → Alpaca` is what populates the cache this class only reads
    (`ports.py`'s `CalendarPort` docstring: the two are connected by the cache, not by calling each
    other directly)."""

    def __init__(self, repository: MarketCalendarCacheRepository) -> None:
        self._repository = repository

    def is_trading_day(self, d: date) -> bool:
        row = self._repository.get(d)
        if row is None:
            raise MarketCalendarCacheMissError(
                f"market_calendar_cache has no row for {d}; fetch it via CalendarPort before "
                "querying MarketClock for this date"
            )
        return row.is_trading_day

    def session_close(self, d: date) -> datetime | None:
        row = self._repository.get(d)
        if row is None:
            raise MarketCalendarCacheMissError(
                f"market_calendar_cache has no row for {d}; fetch it via CalendarPort before "
                "querying MarketClock for this date"
            )
        return row.session_close_at
