"""`market_calendar_cache` (S4 §3.4, ADR 12) — `MarketClock` reads it via a `TradingCalendar`
adapter (`trading_calendar.py` in this package); `CalendarPort → Alpaca` populates it.

**A cache miss is never a holiday (S4 §3.4).** This table is a cache keyed on `market_date`, not a
bitemporal correction ledger like `daily_close` — a row is upserted in place as the source of truth
for that date, since "was 2026-01-01 a trading day" has exactly one right answer, not a history of
corrected answers. An absent row means the calendar has not been fetched for that date yet, which
`MarketCalendarCacheRepository.get()` returning `None` must let the caller distinguish from
`is_trading_day = False` — collapsing the two is exactly the bug this table exists to prevent.
"""

from __future__ import annotations

from datetime import date as date_  # noqa: TC003 -- SQLAlchemy resolves annotations at import time.
from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values
from app.models.marketdata.daily_close import MarketDataSource

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class MarketCalendarCache(Base):
    __tablename__ = "market_calendar_cache"

    market_date: Mapped[date_] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(nullable=False)
    session_open_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    source: Mapped[MarketDataSource] = mapped_column(
        SQLAlchemyEnum(MarketDataSource, name="market_data_source", values_callable=enum_values),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MarketCalendarCacheRepository(BaseRepository[MarketCalendarCache]):
    """No `customer_id_column`: the calendar is not tenant-scoped. Not append-only: this is a
    cache upserted in place (module docstring), unlike `daily_close`'s bitemporal correction
    trail."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=MarketCalendarCache)

    def get(self, market_date: date_) -> MarketCalendarCache | None:
        """`None` means "not yet fetched" -- never conflate with a fetched `is_trading_day=False`
        row (module docstring)."""
        return (
            self.session.query(MarketCalendarCache)
            .filter_by(market_date=market_date)
            .first()
        )

    def upsert(self, row: MarketCalendarCache) -> MarketCalendarCache:
        """Insert, or replace in place if this date was already cached (e.g. a provider
        correction to a previously-fetched half-day)."""
        existing = self.get(row.market_date)
        if existing is None:
            self.add(row)
            return row
        existing.is_trading_day = row.is_trading_day
        existing.session_open_at = row.session_open_at
        existing.session_close_at = row.session_close_at
        existing.source = row.source
        existing.recorded_at = row.recorded_at
        return existing
