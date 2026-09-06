"""`FakeCalendarAdapter` — an in-memory `CalendarPort` for the contract suite and unit tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

    from app.integrations.ports import TradingDayInfo


class FakeCalendarAdapter:
    """Trading days are seeded explicitly via `set_trading_day`; querying an unseeded date raises,
    matching a real provider call for a date nobody has asked about yet rather than guessing."""

    def __init__(self) -> None:
        self._days: dict[date, TradingDayInfo] = {}

    def set_trading_day(self, info: TradingDayInfo) -> None:
        self._days[info.market_date] = info

    def get_trading_day(self, *, market_date: date) -> TradingDayInfo:
        try:
            return self._days[market_date]
        except KeyError as exc:
            raise KeyError(f"no fake trading-day data seeded for {market_date}") from exc


__all__ = ["FakeCalendarAdapter"]
