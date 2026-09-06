"""`AlpacaCalendarAdapter` (S4 §3.4, ADR 12) — `CalendarPort → Alpaca`. Populates
`market_calendar_cache`; `MarketClock` queries it via `CachedTradingCalendar`, never this directly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetCalendarRequest

from app.core.clock import MARKET_TIMEZONE
from app.integrations.ports import TradingDayInfo

if TYPE_CHECKING:
    from datetime import date


class AlpacaCalendarAdapter:
    """An empty `get_calendar` result means `market_date` is not a trading day (weekend/holiday)."""

    def __init__(self, *, api_key_id: str, api_secret_key: str, paper: bool = True) -> None:
        self._client = TradingClient(api_key=api_key_id, secret_key=api_secret_key, paper=paper)

    def get_trading_day(self, *, market_date: date) -> TradingDayInfo:
        calendars = self._client.get_calendar(
            GetCalendarRequest(start=market_date, end=market_date)
        )
        if not isinstance(calendars, list):  # pragma: no cover - raw_data=False is never set here
            raise TypeError(f"expected a list of Calendar, got {type(calendars).__name__}")
        if not calendars:
            return TradingDayInfo(
                market_date=market_date,
                is_trading_day=False,
                session_open_at=None,
                session_close_at=None,
            )
        calendar = calendars[0]
        return TradingDayInfo(
            market_date=market_date,
            is_trading_day=True,
            session_open_at=calendar.open.replace(tzinfo=MARKET_TIMEZONE),
            session_close_at=calendar.close.replace(tzinfo=MARKET_TIMEZONE),
        )


__all__ = ["AlpacaCalendarAdapter"]
