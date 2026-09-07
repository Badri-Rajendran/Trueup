"""`PortfolioPerformanceService` (ADR 26) — folds stored `sub_period_return` rows into an ordered
`[{date, value}]` series plus a cumulative time-weighted return, for the Portfolio page's
performance chart.

This is the live/as-of-now view (`Watermark.live()`, never an ad-hoc `datetime.now()` inlined
here). `GET /api/v1/statements` remains the authoritative *as-published* series (ADR 6) -- this
service never reads `published_snapshot` and never substitutes for it. `range` is a required
keyword argument with no default (ADR 6/14's no-silent-default convention for a bitemporal-adjacent
read); only the controller may default the raw query parameter before calling in.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from app.services.valuation.twr_service import TwrService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import date
    from decimal import Decimal

    from app.core.money import Money
    from app.core.watermark import Watermark
    from app.models.marketdata.sub_period_return import SubPeriodReturn
    from app.services.valuation.uow import ValuationUnitOfWork

PerformanceRange = Literal["1m", "3m", "6m", "1y", "all"]

_RANGE_MONTHS: dict[str, int] = {"1m": 1, "3m": 3, "6m": 6, "1y": 12}


@dataclass(frozen=True, slots=True)
class PerformancePoint:
    as_of_date: date
    value: Money


@dataclass(frozen=True, slots=True)
class PortfolioPerformance:
    customer_id: uuid.UUID
    range: PerformanceRange
    period_start: date | None
    """`None` when no `sub_period_return` coverage exists in the requested range yet (ADR 26) --
    an empty, not-yet-computed series, not an error."""
    period_end: date
    cumulative_twr: Decimal
    is_provisional: bool
    points: tuple[PerformancePoint, ...]


class PortfolioPerformanceService:
    def __init__(self, uow: ValuationUnitOfWork) -> None:
        self._uow = uow

    def performance(
        self,
        customer_id: uuid.UUID,
        *,
        performance_range: PerformanceRange,
        as_of: Watermark,
        today: date,
    ) -> PortfolioPerformance:
        start_date = self._range_start(performance_range, today)
        sub_periods = self._uow.sub_period_returns.list_in_range(
            customer_id=customer_id, start_date=start_date, end_date=today, as_of=as_of
        )
        return PortfolioPerformance(
            customer_id=customer_id,
            range=performance_range,
            period_start=sub_periods[0].sub_period_start if sub_periods else None,
            period_end=today,
            cumulative_twr=TwrService.link(sub_periods),
            is_provisional=any(row.is_provisional for row in sub_periods),
            points=self._to_points(sub_periods),
        )

    @staticmethod
    def _to_points(sub_periods: Sequence[SubPeriodReturn]) -> tuple[PerformancePoint, ...]:
        if not sub_periods:
            return ()
        points = [
            PerformancePoint(
                as_of_date=sub_periods[0].sub_period_start, value=sub_periods[0].value_begin
            )
        ]
        points.extend(
            PerformancePoint(as_of_date=row.sub_period_end, value=row.value_end)
            for row in sub_periods
        )
        return tuple(points)

    @staticmethod
    def _range_start(performance_range: PerformanceRange, today: date) -> date | None:
        if performance_range == "all":
            return None
        return _subtract_months(today, _RANGE_MONTHS[performance_range])


def _subtract_months(on_date: date, months: int) -> date:
    """Calendar-month subtraction, clamping the day to the target month's length (e.g. Mar 31
    minus 1 month -> Feb 28/29) -- stdlib only, no `dateutil` dependency in this codebase."""
    month_index = on_date.month - 1 - months
    year = on_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(on_date.day, calendar.monthrange(year, month)[1])
    return on_date.replace(year=year, month=month, day=day)


__all__ = [
    "PerformancePoint",
    "PerformanceRange",
    "PortfolioPerformance",
    "PortfolioPerformanceService",
]
