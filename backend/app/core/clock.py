"""MarketClock: the only code allowed to convert a UTC instant into a market day (ADR 12, S0 §10.8).

Every "daily," "morning," and "T+1" concept in the brief (valuation, reconciliation, settlement) is
a US market-day concept, not a server-clock-day concept. New York sits behind UTC, so a stored UTC
instant in the evening is already tomorrow in UTC while still today in New York; code that calls
`.date()` on a UTC instant directly gets that backwards, and the wrongness silently shifts by an
hour every time US daylight saving flips. `MarketClock.market_date()` is the one place that
conversion happens, so no other module can get it wrong independently (ADR 12).

Layering constraint (S0 §3): `app/core/` imports nothing else under `app/`, so `MarketClock`
cannot read `market_calendar_cache` or import a model. `TradingCalendar` is the seam: a `Protocol`
this module owns, injected at construction. `InMemoryTradingCalendar` (below) is the calendar for
tests and the fake adapter now; the database-backed implementation reading `market_calendar_cache`
arrives in Wave 4 (S4) as another `TradingCalendar`, without this module changing at all.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

MARKET_TIMEZONE = ZoneInfo("America/New_York")
"""ADR 12: the single timezone every daily-boundary computation in the system anchors to."""

_MAX_CALENDAR_SEARCH_DAYS = 14
"""Longest real US market closure (year-end plus a holiday) is a handful of days; this is a
generous bound whose only job is turning a misconfigured calendar into a loud error instead of an
infinite loop."""


class CalendarExhaustedError(RuntimeError):
    """No trading day was found within the bounded search window.

    This means the injected `TradingCalendar` is misconfigured (e.g. every day marked a holiday),
    not that the market is closed for an unusually long stretch — a real closure is always far
    shorter than `_MAX_CALENDAR_SEARCH_DAYS`.
    """


@runtime_checkable
class TradingCalendar(Protocol):
    """The market-calendar seam `app/core/` depends on without importing a model.

    A database-backed implementation reading `market_calendar_cache` (S4) and
    `InMemoryTradingCalendar` (tests, and the fake adapter) both satisfy this without either one
    knowing about the other.
    """

    def is_trading_day(self, d: date) -> bool:
        """Whether `d` is a US market trading day (not a weekend, not a holiday)."""
        ...

    def session_close(self, d: date) -> datetime | None:
        """The instant trading ends for `d`, tz-aware in `MARKET_TIMEZONE`.

        `None` if `d` is not a trading day. A half day returns its real early-close instant, never
        an assumed 4pm (S0 §10.8).
        """
        ...


class InMemoryTradingCalendar:
    """A `TradingCalendar` defined by an explicit holiday and half-day set.

    A trading day is any weekday not listed in `holidays`. `half_days` maps a date to its close
    time in `MARKET_TIMEZONE` (e.g. 1pm on the day after Thanksgiving); every other trading day
    closes at 4pm.
    """

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
    """Converts a UTC instant into "which market day is this" — S0 §10.8's one allowed seam.

    Constructor-injected with a `TradingCalendar` so this class never depends on how the calendar
    is sourced (in-memory fixture today, `market_calendar_cache` from S4 later).
    """

    def __init__(self, calendar: TradingCalendar) -> None:
        self._calendar = calendar

    def market_date(self, instant: datetime) -> date:
        """The America/New_York calendar date `instant` falls on.

        Rejects a naive `instant` rather than assuming a timezone: a naive datetime silently
        assumes the server's local zone, which is exactly the off-by-one-day bug ADR 12 exists to
        prevent.
        """
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
        """Step `n` trading days from `d` — T+1 settlement is `add_trading_days(fill_date, 1)`.

        `d` itself need not be a trading day; stepping simply starts from it. `n` may be negative
        to step backward, or zero to return `d` unchanged.
        """
        step = self.next_trading_day if n >= 0 else self.previous_trading_day
        current = d
        for _ in range(abs(n)):
            current = step(current)
        return current
