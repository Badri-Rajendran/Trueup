"""`valuation_run` (S4 §3.2) — one row per `market_date` `DailyValuationJob` processes.

Not in the team-lead brief's explicit file list for this wave, but named and schema'd in full by S4
§3.2 and required by §4/§6/§8 case 4 (`ValuationService`/`TwrService` both need to know whether a
day's valuation was `complete` or `partial`) and by the foundation spec's own S4 surface map
(`DailyValuationJob`). Built here rather than skipped -- omitting it would leave "the whole-book
`partial` condition" (S4 §6) unimplementable, which is a spec requirement, not an enhancement.

Upserted in place per `market_date`, like `market_calendar_cache` -- "did today's valuation run
complete" has one right answer per day, not a bitemporal correction history.
"""

from __future__ import annotations

from datetime import date as date_  # noqa: TC003 -- SQLAlchemy resolves annotations at import time.
from datetime import datetime  # noqa: TC003
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Integer
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ValuationRunStatus(StrEnum):
    PENDING = "pending"
    COMPLETE = "complete"
    PARTIAL = "partial"


class ValuationRun(Base):
    __tablename__ = "valuation_run"

    market_date: Mapped[date_] = mapped_column(Date, primary_key=True)
    securities_expected: Mapped[int] = mapped_column(Integer, nullable=False)
    securities_confirmed: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ValuationRunStatus] = mapped_column(
        SQLAlchemyEnum(
            ValuationRunStatus, name="valuation_run_status", values_callable=enum_values
        ),
        nullable=False,
        default=ValuationRunStatus.PENDING,
        server_default=ValuationRunStatus.PENDING.value,
    )
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ValuationRunRepository(BaseRepository[ValuationRun]):
    """No `customer_id_column`: a valuation run is whole-book, not tenant-scoped."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ValuationRun)

    def get(self, market_date: date_) -> ValuationRun | None:
        return self.session.query(ValuationRun).filter_by(market_date=market_date).first()

    def upsert(self, row: ValuationRun) -> ValuationRun:
        existing = self.get(row.market_date)
        if existing is None:
            self.add(row)
            return row
        existing.securities_expected = row.securities_expected
        existing.securities_confirmed = row.securities_confirmed
        existing.status = row.status
        existing.recorded_at = row.recorded_at
        return existing
