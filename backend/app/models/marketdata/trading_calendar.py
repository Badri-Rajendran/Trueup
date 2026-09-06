"""`CachedTradingCalendar` — `TradingCalendar` (`app/core/clock.py`) implementation reading
`market_calendar_cache` (S4 §3.4, ADR 12). A cache miss raises `MarketCalendarCacheMissError`,
never silently reads as a holiday.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date, datetime

    from app.models.marketdata.market_calendar_cache import MarketCalendarCacheRepository


class MarketCalendarCacheMissError(RuntimeError):
    """`market_calendar_cache` has no row for this date yet; distinct from a fetched holiday (S4 §3.4)."""


class CachedTradingCalendar:
    """Satisfies `app.core.clock.TradingCalendar` by querying `market_calendar_cache`."""

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
