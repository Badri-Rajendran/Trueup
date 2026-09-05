"""`CalendarPort` contract (S4 §3.4, ADR 12): the same assertions against `FakeCalendarAdapter`
and, when Alpaca sandbox credentials are configured, `AlpacaCalendarAdapter`.
"""

from __future__ import annotations

import os
from datetime import UTC, date, datetime

import pytest

from app.integrations.fake.fake_calendar import FakeCalendarAdapter
from app.integrations.ports import CalendarPort, TradingDayInfo


def _assert_trading_day_contract(port: CalendarPort, *, trading_day: date) -> None:
    info = port.get_trading_day(market_date=trading_day)
    assert info.market_date == trading_day
    assert info.is_trading_day is True
    assert info.session_open_at is not None
    assert info.session_close_at is not None
    assert info.session_open_at < info.session_close_at


def _assert_holiday_contract(port: CalendarPort, *, holiday: date) -> None:
    info = port.get_trading_day(market_date=holiday)
    assert info.market_date == holiday
    assert info.is_trading_day is False
    assert info.session_open_at is None
    assert info.session_close_at is None


def test_fake_calendar_adapter_satisfies_the_contract() -> None:
    adapter = FakeCalendarAdapter()
    trading_day = date(2026, 9, 8)
    holiday = date(2026, 1, 1)
    adapter.set_trading_day(
        TradingDayInfo(
            market_date=trading_day,
            is_trading_day=True,
            session_open_at=datetime(2026, 9, 8, 13, 30, tzinfo=UTC),
            session_close_at=datetime(2026, 9, 8, 20, 0, tzinfo=UTC),
        )
    )
    adapter.set_trading_day(
        TradingDayInfo(
            market_date=holiday, is_trading_day=False, session_open_at=None, session_close_at=None
        )
    )

    _assert_trading_day_contract(adapter, trading_day=trading_day)
    _assert_holiday_contract(adapter, holiday=holiday)


@pytest.mark.requires_credentials
@pytest.mark.skipif(
    not (os.environ.get("ALPACA_API_KEY_ID") and os.environ.get("ALPACA_API_SECRET_KEY")),
    reason="requires real Alpaca paper credentials (ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY)",
)
def test_real_alpaca_calendar_adapter_satisfies_the_contract() -> None:
    from app.integrations.alpaca.calendar_adapter import AlpacaCalendarAdapter

    adapter = AlpacaCalendarAdapter(
        api_key_id=os.environ["ALPACA_API_KEY_ID"],
        api_secret_key=os.environ["ALPACA_API_SECRET_KEY"],
    )
    _assert_trading_day_contract(adapter, trading_day=date(2025, 1, 2))
    _assert_holiday_contract(adapter, holiday=date(2025, 1, 1))  # New Year's Day
