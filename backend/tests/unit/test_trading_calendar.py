"""`CachedTradingCalendar`: a cache miss must never be conflated with a holiday (S4 §3.4)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.models.marketdata.daily_close import MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.trading_calendar import (
    CachedTradingCalendar,
    MarketCalendarCacheMissError,
)


class _FakeCalendarCacheRepo:
    def __init__(self) -> None:
        self._rows: dict[date, MarketCalendarCache] = {}

    def seed(self, row: MarketCalendarCache) -> None:
        self._rows[row.market_date] = row

    def get(self, market_date: date) -> MarketCalendarCache | None:
        return self._rows.get(market_date)


def _row(
    market_date: date, *, is_trading_day: bool, close_at: datetime | None = None
) -> MarketCalendarCache:
    return MarketCalendarCache(
        market_date=market_date,
        is_trading_day=is_trading_day,
        session_open_at=None,
        session_close_at=close_at,
        source=MarketDataSource.LIVE,
        recorded_at=datetime.now(UTC),
    )


def test_is_trading_day_reflects_a_fetched_row() -> None:
    repo = _FakeCalendarCacheRepo()
    trading_day = date(2026, 9, 8)  # a Tuesday
    repo.seed(_row(trading_day, is_trading_day=True))
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    assert calendar.is_trading_day(trading_day) is True


def test_is_trading_day_reflects_a_fetched_holiday_row() -> None:
    repo = _FakeCalendarCacheRepo()
    holiday = date(2026, 1, 1)
    repo.seed(_row(holiday, is_trading_day=False))
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    assert calendar.is_trading_day(holiday) is False


def test_cache_miss_raises_rather_than_reading_as_a_holiday() -> None:
    """S4 §3.4: an unfetched date is an operational condition, never a silent `False`."""
    repo = _FakeCalendarCacheRepo()
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    with pytest.raises(MarketCalendarCacheMissError):
        calendar.is_trading_day(date(2026, 9, 9))


def test_session_close_cache_miss_also_raises() -> None:
    repo = _FakeCalendarCacheRepo()
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    with pytest.raises(MarketCalendarCacheMissError):
        calendar.session_close(date(2026, 9, 9))


def test_session_close_returns_the_real_stored_instant_for_a_trading_day() -> None:
    repo = _FakeCalendarCacheRepo()
    trading_day = date(2026, 9, 8)
    close_at = datetime(2026, 9, 8, 16, 0, tzinfo=UTC)
    repo.seed(_row(trading_day, is_trading_day=True, close_at=close_at))
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    assert calendar.session_close(trading_day) == close_at


def test_session_close_is_none_for_a_fetched_holiday() -> None:
    repo = _FakeCalendarCacheRepo()
    holiday = date(2026, 1, 1)
    repo.seed(_row(holiday, is_trading_day=False))
    calendar = CachedTradingCalendar(repo)  # type: ignore[arg-type]

    assert calendar.session_close(holiday) is None
