"""The only code allowed to convert a UTC instant into a market day (ADR 12, S0 §10.8)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
"""ADR 12: the timezone every daily-boundary computation anchors to."""

_MAX_CALENDAR_SEARCH_DAYS = 14
"""Bound that turns a misconfigured calendar into a loud error instead of an infinite loop."""


class CalendarExhaustedError(RuntimeError):
    """No trading day found in the search window — the injected calendar is misconfigured."""


@runtime_checkable
class TradingCalendar(Protocol):
    """Market-calendar seam `app/core/` depends on without importing a model."""

    def is_trading_day(self, d: date) -> bool:
        """Whether `d` is a US market trading day (not a weekend, not a holiday)."""
        ...

    def session_close(self, d: date) -> datetime | None:
        """Instant trading ends for `d`, tz-aware; `None` if `d` is not a trading day."""
        ...


class InMemoryTradingCalendar:
    """A `TradingCalendar` defined by an explicit holiday and half-day set."""

    def __init__(
        self,
        *,
        holidays: set[date] | None = None,
        half_days: dict[date, time] | None = None,
    ) -> None:
        self._holidays = holidays if holidays is not None else set()
        self._half_days = half_days if half_days is not None else {}

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays

    def session_close(self, d: date) -> datetime | None:
        if not self.is_trading_day(d):
            return None
        close_time = self._half_days.get(d, time(16, 0))
        return datetime.combine(d, close_time, tzinfo=MARKET_TIMEZONE)


class MarketClock:
    """Converts a UTC instant into "which market day is this" — S0 §10.8's one allowed seam."""

    def __init__(self, calendar: TradingCalendar) -> None:
        self._calendar = calendar

    def market_date(self, instant: datetime) -> date:
        """The America/New_York calendar date `instant` falls on. Rejects a naive `instant`."""
        if instant.tzinfo is None:
            raise ValueError(
                "market_date() requires a timezone-aware datetime; a naive value silently "
                "assumes the server's local zone (ADR 12)."
            )
        return instant.astimezone(MARKET_TIMEZONE).date()

    def is_trading_day(self, d: date) -> bool:
        return self._calendar.is_trading_day(d)

    def session_close(self, d: date) -> datetime | None:
        return self._calendar.session_close(d)

    def next_trading_day(self, d: date) -> date:
        """The first trading day strictly after `d`."""
        candidate = d
        for _ in range(_MAX_CALENDAR_SEARCH_DAYS):
            candidate += timedelta(days=1)
            if self._calendar.is_trading_day(candidate):
                return candidate
        raise CalendarExhaustedError(
            f"no trading day found within {_MAX_CALENDAR_SEARCH_DAYS} days after {d}"
        )

    def previous_trading_day(self, d: date) -> date:
        """The first trading day strictly before `d`."""
        candidate = d
        for _ in range(_MAX_CALENDAR_SEARCH_DAYS):
            candidate -= timedelta(days=1)
            if self._calendar.is_trading_day(candidate):
                return candidate
        raise CalendarExhaustedError(
            f"no trading day found within {_MAX_CALENDAR_SEARCH_DAYS} days before {d}"
        )

    def add_trading_days(self, d: date, n: int) -> date:
        """Step `n` trading days from `d` — T+1 settlement is `add_trading_days(fill_date, 1)`."""
        step = self.next_trading_day if n >= 0 else self.previous_trading_day
        current = d
        for _ in range(abs(n)):
            current = step(current)
        return current
