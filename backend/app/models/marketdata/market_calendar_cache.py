"""`market_calendar_cache` (S4 §3.4, ADR 12) — read via `TradingCalendar`/`trading_calendar.py`.

Upserted in place, keyed on `market_date`. A cache miss (`get()` returns `None`) is never a holiday.
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
    """No `customer_id_column`: not tenant-scoped. Not append-only: a cache upserted in place."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=MarketCalendarCache)

    def get(self, market_date: date_) -> MarketCalendarCache | None:
        """`None` means "not yet fetched"; never conflate with a fetched `is_trading_day=False` row."""
        return (
            self.session.query(MarketCalendarCache)
            .filter_by(market_date=market_date)
            .first()
        )

    def upsert(self, row: MarketCalendarCache) -> MarketCalendarCache:
        """Insert, or replace in place if this date was already cached."""
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
