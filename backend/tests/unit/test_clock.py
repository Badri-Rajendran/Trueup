"""`MarketClock`: a UTC instant is not "which day is it" until converted, across both US DST
offsets (ADR 12, S0 §10.8)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time

import pytest

from app.core.clock import CalendarExhaustedError, InMemoryTradingCalendar, MarketClock

THANKSGIVING_2026 = date(2026, 11, 26)
DAY_AFTER_THANKSGIVING_2026 = date(2026, 11, 27)
NEW_YEARS_DAY_2026 = date(2026, 1, 1)


@pytest.fixture
def calendar() -> InMemoryTradingCalendar:
    return InMemoryTradingCalendar(
        holidays={NEW_YEARS_DAY_2026, THANKSGIVING_2026},
        half_days={DAY_AFTER_THANKSGIVING_2026: time(13, 0)},
    )


@pytest.fixture
def clock(calendar: InMemoryTradingCalendar) -> MarketClock:
    return MarketClock(calendar)


# --- market_date(): naive rejection --------------------------------------------------------


def test_market_date_rejects_naive_datetime(clock: MarketClock) -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.market_date(datetime(2026, 3, 9, 20, 30))  # noqa: DTZ001


# --- market_date(): the ADR-12 off-by-one bug, in both US DST offsets ----------------------


def test_market_date_late_utc_instant_still_previous_ny_day_in_winter_est(
    clock: MarketClock,
) -> None:
    """9:30pm EST on Jan 15 is 2:30am UTC on Jan 16 -- must resolve to Jan 15."""
    instant = datetime(2026, 1, 16, 2, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 1, 15)


def test_market_date_late_utc_instant_still_previous_ny_day_in_summer_edt(
    clock: MarketClock,
) -> None:
    """9:30pm EDT on Jul 15 is 1:30am UTC on Jul 16 -- must resolve to Jul 15."""
    instant = datetime(2026, 7, 16, 1, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 7, 15)


# --- market_date(): across the actual DST transition, in both directions -------------------


def test_market_date_around_spring_forward_before_transition(clock: MarketClock) -> None:
    """Fri Mar 6 2026 (EST, UTC-5) is the trading day before the Mar 8 spring-forward."""
    close_plus_30min = datetime(2026, 3, 6, 21, 30, tzinfo=UTC)
    assert clock.market_date(close_plus_30min) == date(2026, 3, 6)


def test_market_date_around_spring_forward_after_transition(clock: MarketClock) -> None:
    """Mon Mar 9 2026 (EDT, UTC-4) is the first trading day after the Mar 8 spring-forward."""
    close_plus_30min = datetime(2026, 3, 9, 20, 30, tzinfo=UTC)
    assert clock.market_date(close_plus_30min) == date(2026, 3, 9)


def test_market_date_late_instant_crossing_spring_forward_boundary(clock: MarketClock) -> None:
    """Late Friday-evening EST instant just before the Mar 8 transition."""
    instant = datetime(2026, 3, 7, 2, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 3, 6)


def test_market_date_late_instant_after_spring_forward_boundary(clock: MarketClock) -> None:
    """Late Monday-evening EDT instant, the first trading evening after the transition."""
    instant = datetime(2026, 3, 10, 1, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 3, 9)


def test_market_date_late_instant_crossing_fall_back_boundary(clock: MarketClock) -> None:
    """Late Friday-evening EDT instant just before the Nov 1 fall-back."""
    instant = datetime(2026, 10, 31, 1, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 10, 30)


def test_market_date_late_instant_after_fall_back_boundary(clock: MarketClock) -> None:
    """Late Monday-evening EST instant, the first trading evening after the fall-back."""
    instant = datetime(2026, 11, 3, 2, 30, tzinfo=UTC)
    assert clock.market_date(instant) == date(2026, 11, 2)


# --- trading-day queries ---------------------------------------------------------------------


def test_weekend_is_not_a_trading_day(clock: MarketClock) -> None:
    assert clock.is_trading_day(date(2026, 1, 17)) is False  # Saturday


def test_holiday_is_not_a_trading_day(clock: MarketClock) -> None:
    assert clock.is_trading_day(NEW_YEARS_DAY_2026) is False  # Thursday, but a holiday


def test_ordinary_weekday_is_a_trading_day(clock: MarketClock) -> None:
    assert clock.is_trading_day(date(2026, 1, 15)) is True  # Thursday


def test_next_trading_day_skips_weekend(clock: MarketClock) -> None:
    friday = date(2026, 1, 16)
    assert clock.next_trading_day(friday) == date(2026, 1, 19)  # Monday


def test_next_trading_day_skips_holiday_and_weekend(clock: MarketClock) -> None:
    """New Year's Day 2026 (Thursday) is a holiday; Friday Jan 2 is the next trading day."""
    assert clock.next_trading_day(date(2025, 12, 31)) == date(2026, 1, 2)


def test_previous_trading_day_skips_weekend(clock: MarketClock) -> None:
    monday = date(2026, 1, 19)
    assert clock.previous_trading_day(monday) == date(2026, 1, 16)  # Friday


def test_calendar_exhausted_raises_rather_than_looping_forever() -> None:
    """A pathological calendar with no trading days must fail loudly, not hang."""

    class _NeverOpen:
        def is_trading_day(self, d: date) -> bool:
            return False

        def session_close(self, d: date) -> datetime | None:
            return None

    never_open_clock = MarketClock(_NeverOpen())
    with pytest.raises(CalendarExhaustedError):
        never_open_clock.next_trading_day(date(2026, 1, 1))


# --- add_trading_days(): T+1 settlement ------------------------------------------------------


def test_add_trading_days_settles_t_plus_1_across_a_weekend(clock: MarketClock) -> None:
    friday_fill = date(2026, 1, 16)
    assert clock.add_trading_days(friday_fill, 1) == date(2026, 1, 19)  # Monday


def test_add_trading_days_zero_returns_the_same_date(clock: MarketClock) -> None:
    assert clock.add_trading_days(date(2026, 1, 15), 0) == date(2026, 1, 15)


def test_add_trading_days_negative_steps_backward(clock: MarketClock) -> None:
    monday = date(2026, 1, 19)
    assert clock.add_trading_days(monday, -1) == date(2026, 1, 16)  # Friday


def test_add_trading_days_multiple_steps_skip_a_holiday(clock: MarketClock) -> None:
    """Dec 31 2025 (Wed) + 2 trading days: Jan 1 is a holiday, so Fri Jan 2 then Mon Jan 5."""
    assert clock.add_trading_days(date(2025, 12, 31), 2) == date(2026, 1, 5)


# --- session_close(): a half day is a real close time, not an assumed 4pm --------------------


def test_session_close_full_trading_day_is_4pm_eastern(clock: MarketClock) -> None:
    close = clock.session_close(date(2026, 1, 15))
    assert close is not None
    assert (close.hour, close.minute) == (16, 0)
    assert close.tzinfo is not None


def test_session_close_half_day_is_the_early_close(clock: MarketClock) -> None:
    close = clock.session_close(DAY_AFTER_THANKSGIVING_2026)
    assert close is not None
    assert (close.hour, close.minute) == (13, 0)


def test_session_close_non_trading_day_is_none(clock: MarketClock) -> None:
    assert clock.session_close(NEW_YEARS_DAY_2026) is None
    assert clock.session_close(date(2026, 1, 17)) is None  # Saturday
