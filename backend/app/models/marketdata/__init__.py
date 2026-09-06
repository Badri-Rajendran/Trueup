"""Market-data aggregates (S4) — securities, closes, the calendar cache, valuation runs, and
stored TWR sub-periods."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.marketdata.daily_close import DailyCloseRepository
from app.models.marketdata.market_calendar_cache import MarketCalendarCacheRepository
from app.models.marketdata.security import SecurityRepository
from app.models.marketdata.sub_period_return import SubPeriodReturnRepository
from app.models.marketdata.valuation_run import ValuationRunRepository


class MarketDataUnitOfWork(UnitOfWork):
    """A `UnitOfWork` exposing the repositories S4 owns (S0 §5's documented extension mechanism)."""

    @cached_property
    def securities(self) -> SecurityRepository:
        return SecurityRepository(self)

    @cached_property
    def daily_closes(self) -> DailyCloseRepository:
        return DailyCloseRepository(self)

    @cached_property
    def calendar_cache(self) -> MarketCalendarCacheRepository:
        return MarketCalendarCacheRepository(self)

    @cached_property
    def valuation_runs(self) -> ValuationRunRepository:
        return ValuationRunRepository(self)

    @cached_property
    def sub_period_returns(self) -> SubPeriodReturnRepository:
        return SubPeriodReturnRepository(self)
