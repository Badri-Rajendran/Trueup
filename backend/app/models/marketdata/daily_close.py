"""`daily_close` (S4 §3.1) — one row per confirmed/stale close a provider ever reported.

Bitemporal, append-only, matching `journal_entry`/`posting`'s posture (ADR 1 extended to price
data): a corrected close for the same `market_date` is a **new row**, never an `UPDATE` -- S6's
restatement mechanism depends on being able to see what the close was *as of* any prior watermark.

**`missing` is never a stored row (S4 §6).** No close arriving at all by the valuation cutoff is
represented by the *absence* of a `confirmed` row for that `(security_id, market_date)` --
`ValuationService` infers `missing` from that absence, exactly as the spec requires ("inferred by
absence, not stored as a row"). The `MISSING` enum member exists for schema completeness (a
provider could in principle report an explicit missing/withdrawn signal) but no code path in this
sub-project writes one.
"""

from __future__ import annotations

import uuid
from datetime import (  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
    date,
    datetime,
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Date as SQLAlchemyDate
from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Price, PriceType
from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class MarketDataSource(StrEnum):
    """NFR-12's "market data live or simulated, clearly labelled" rule -- shared by `daily_close`
    and `market_calendar_cache` (S4 §3.1/§3.4)."""

    LIVE = "live"
    SIMULATED = "simulated"


class DailyCloseStatus(StrEnum):
    CONFIRMED = "confirmed"
    STALE = "stale"
    MISSING = "missing"
    """Never written by this sub-project's own code paths -- see module docstring."""


class DailyClose(Base):
    __tablename__ = "daily_close"
    __table_args__ = (
        UniqueConstraint(
            "security_id",
            "market_date",
            "recorded_at",
            name="uq_daily_close_security_market_recorded",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    security_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("security.id"), nullable=False
    )
    market_date: Mapped[date] = mapped_column(SQLAlchemyDate, nullable=False)
    close_price: Mapped[Price] = mapped_column(PriceType, nullable=False)
    source: Mapped[MarketDataSource] = mapped_column(
        SQLAlchemyEnum(MarketDataSource, name="market_data_source", values_callable=enum_values),
        nullable=False,
    )
    status: Mapped[DailyCloseStatus] = mapped_column(
        SQLAlchemyEnum(DailyCloseStatus, name="daily_close_status", values_callable=enum_values),
        nullable=False,
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DailyCloseRepository(BaseRepository[DailyClose]):
    """No `customer_id_column`: prices are not tenant-scoped. Append-only (S4 §3.1) -- a
    correction is always a new row with a later `recorded_at`, never an `UPDATE`."""

    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=DailyClose, recorded_at_column=DailyClose.recorded_at)

    def latest_confirmed(self, *, security_id: uuid.UUID, market_date: date) -> DailyClose | None:
        """The latest-`recorded_at` `confirmed` close for this security/date (S4 §4's
        `value_book` read, S4 §8 case 5: always the newest correction, however many followed)."""
        return (
            self.session.query(DailyClose)
            .filter_by(
                security_id=security_id,
                market_date=market_date,
                status=DailyCloseStatus.CONFIRMED,
            )
            .order_by(DailyClose.recorded_at.desc())
            .first()
        )

    def latest(self, *, security_id: uuid.UUID, market_date: date) -> DailyClose | None:
        """The latest-`recorded_at` row regardless of status -- used to classify `stale` vs.
        genuinely absent (S4 §6)."""
        return (
            self.session.query(DailyClose)
            .filter_by(security_id=security_id, market_date=market_date)
            .order_by(DailyClose.recorded_at.desc())
            .first()
        )
