"""`DailyValuationJob` (S4): fetches the day's trading-calendar status and closing prices, and
records `valuation_run`'s whole-book completeness (S4 §3.2/§6).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.db import DbRole
from app.core.money import Units
from app.core.uow import SessionRole
from app.jobs.base import JobOutcome, ScheduledJob, default_job_uow
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.valuation_run import ValuationRun, ValuationRunStatus
from app.models.ops.job_run import JobCadence
from app.services.valuation.uow import ValuationUnitOfWork

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from app.integrations.ports import CalendarPort, MarketDataPort
    from app.jobs.base import JobUnitOfWork


class _DailyValuationWorkUnitOfWork(ValuationUnitOfWork):
    """Admin/worker-role UoW for the job's own writes, separate from the `JobRun` transaction."""


def _default_work_uow_factory() -> _DailyValuationWorkUnitOfWork:
    return _DailyValuationWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


class DailyValuationJob(ScheduledJob):
    job_name = "daily_valuation"
    cadence = JobCadence.DAILY

    def __init__(
        self,
        *,
        market_data_port: MarketDataPort,
        calendar_port: CalendarPort,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[[], _DailyValuationWorkUnitOfWork] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._market_data_port = market_data_port
        self._calendar_port = calendar_port
        self._work_uow_factory = work_uow_factory
        self._market_date: date | None = None

    def run(self, *, market_date: date) -> JobOutcome:
        self._market_date = market_date
        return super().run(market_date=market_date)

    def perform(self) -> None:
        if self._market_date is None:  # pragma: no cover - defensive
            raise RuntimeError("DailyValuationJob.perform() called before run()")
        market_date = self._market_date
        now = datetime.now(UTC)

        with self._work_uow_factory() as uow:
            trading_day = self._calendar_port.get_trading_day(market_date=market_date)
            uow.calendar_cache.upsert(
                MarketCalendarCache(
                    market_date=market_date,
                    is_trading_day=trading_day.is_trading_day,
                    session_open_at=trading_day.session_open_at,
                    session_close_at=trading_day.session_close_at,
                    source=MarketDataSource.LIVE,
                    recorded_at=now,
                )
            )

            if not trading_day.is_trading_day:
                # S4 §6: a non-trading day is never expected to have a valuation_run at all.
                uow.commit()
                return

            security_ids = self._securities_with_positions(uow, market_date)
            confirmed = 0
            for security_id in security_ids:
                security = uow.securities.get_by_id(security_id)
                if security is None:  # pragma: no cover - defensive
                    continue
                quote = self._market_data_port.get_close(
                    symbol=security.symbol, market_date=market_date
                )
                if quote is None:
                    continue  # S4 §6: missing is inferred by absence, never a stored row.
                uow.daily_closes.add(
                    DailyClose(
                        security_id=security_id,
                        market_date=market_date,
                        close_price=quote.close_price,
                        source=MarketDataSource.LIVE,
                        status=DailyCloseStatus.CONFIRMED,
                        recorded_at=now,
                    )
                )
                confirmed += 1

            status = (
                ValuationRunStatus.COMPLETE
                if confirmed == len(security_ids)
                else ValuationRunStatus.PARTIAL
            )
            uow.valuation_runs.upsert(
                ValuationRun(
                    market_date=market_date,
                    securities_expected=len(security_ids),
                    securities_confirmed=confirmed,
                    status=status,
                    recorded_at=now,
                )
            )
            uow.commit()

    @staticmethod
    def _securities_with_positions(
        uow: _DailyValuationWorkUnitOfWork, market_date: date
    ) -> list[uuid.UUID]:
        """Every security with a nonzero position as of `market_date`, across all customers."""
        statement = (
            select(Account.security_id, func.coalesce(func.sum(Posting.quantity_units), 0))
            .join(Posting, Posting.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
            .where(
                Account.role == AccountRole.POSITION_UNITS,
                JournalEntry.effective_date <= market_date,
            )
            .group_by(Account.security_id)
        )
        rows = uow.session.execute(statement).all()
        return [
            security_id
            for security_id, units in rows
            if security_id is not None and units != Units("0")
        ]


__all__ = ["DailyValuationJob"]
