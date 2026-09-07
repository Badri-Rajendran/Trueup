"""`PortfolioPerformanceService` (ADR 26) against real Postgres -- exercises
`SubPeriodReturnRepository.list_in_range()`'s watermarked, tenant-scoped read end to end, the same
wiring `GET /api/v1/portfolios/performance` uses.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.db import DbRole
from app.core.money import Money
from app.core.uow import SessionRole
from app.core.watermark import Watermark
from app.extensions import dispose_engines, init_engines
from app.models.identity.customer import Customer
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.services.valuation.portfolio_performance_service import PortfolioPerformanceService
from app.services.valuation.uow import ValuationUnitOfWork

TODAY = date(2026, 9, 5)

_TABLES = [Customer.__table__, SubPeriodReturn.__table__]

pytestmark = pytest.mark.usefixtures("_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _seed_customer(db_committing: Session) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    db_committing.add(customer)
    db_committing.commit()
    return customer.id


def _sub_period(
    customer_id: uuid.UUID,
    *,
    start: date,
    end: date,
    return_pct: Decimal,
    value_begin: Money,
    value_end: Money,
    is_provisional: bool = False,
    recorded_at: datetime | None = None,
) -> SubPeriodReturn:
    row = SubPeriodReturn(
        customer_id=customer_id,
        sub_period_start=start,
        sub_period_end=end,
        return_pct=return_pct,
        value_begin=value_begin,
        value_end=value_end,
        flow_amount=Money("0.0000"),
        is_provisional=is_provisional,
    )
    if recorded_at is not None:
        # Explicit, deterministic `recorded_at` rather than the server-side `now()` default --
        # avoids any dependency on client/server clock skew for a watermark-boundary test.
        row.recorded_at = recorded_at
    return row


def _performance(
    customer_id: uuid.UUID,
    *,
    performance_range: str,
    today: date = TODAY,
    as_of: Watermark | None = None,
):
    with ValuationUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        return PortfolioPerformanceService(uow).performance(
            customer_id,
            performance_range=performance_range,  # type: ignore[arg-type]
            as_of=as_of or Watermark.live(),
            today=today,
        )


def test_folds_a_single_sub_period_into_two_points(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    db_committing.add(
        _sub_period(
            customer_id,
            start=TODAY - timedelta(days=10),
            end=TODAY,
            return_pct=Decimal("0.0500000000"),
            value_begin=Money("10000.0000"),
            value_end=Money("10500.0000"),
        )
    )
    db_committing.commit()

    result = _performance(customer_id, performance_range="1m")

    assert result.period_start == TODAY - timedelta(days=10)
    assert result.period_end == TODAY
    assert result.cumulative_twr == Decimal("0.0500000000")
    assert result.is_provisional is False
    assert [(p.as_of_date, p.value) for p in result.points] == [
        (TODAY - timedelta(days=10), Money("10000.0000")),
        (TODAY, Money("10500.0000")),
    ]


def test_range_excludes_sub_periods_outside_the_window(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    db_committing.add_all(
        [
            _sub_period(
                customer_id,
                start=TODAY - timedelta(days=200),
                end=TODAY - timedelta(days=190),
                return_pct=Decimal("0.0200000000"),
                value_begin=Money("9000.0000"),
                value_end=Money("9180.0000"),
            ),
            _sub_period(
                customer_id,
                start=TODAY - timedelta(days=10),
                end=TODAY,
                return_pct=Decimal("0.0500000000"),
                value_begin=Money("10000.0000"),
                value_end=Money("10500.0000"),
            ),
        ]
    )
    db_committing.commit()

    one_month = _performance(customer_id, performance_range="1m")
    all_range = _performance(customer_id, performance_range="all")

    assert len(one_month.points) == 2
    assert one_month.cumulative_twr == Decimal("0.0500000000")
    assert len(all_range.points) == 3
    # (1.02 * 1.05) - 1, quantized to sub_period_return.return_pct's NUMERIC(18,10) scale.
    assert all_range.cumulative_twr == Decimal("0.0710000000")
    assert all_range.period_start == TODAY - timedelta(days=200)


def test_no_coverage_is_an_empty_series_not_an_error(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)

    result = _performance(customer_id, performance_range="1y")

    assert result.period_start is None
    assert result.points == ()
    assert result.cumulative_twr == Decimal("0.0000000000")


def test_watermark_excludes_a_row_recorded_after_the_cutoff(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    cutoff = datetime(2026, 9, 1, tzinfo=UTC)
    db_committing.add(
        _sub_period(
            customer_id,
            start=TODAY - timedelta(days=10),
            end=TODAY,
            return_pct=Decimal("0.0500000000"),
            value_begin=Money("10000.0000"),
            value_end=Money("10500.0000"),
            recorded_at=cutoff + timedelta(days=1),
        )
    )
    db_committing.commit()

    result = _performance(
        customer_id, performance_range="all", as_of=Watermark.as_published(cutoff)
    )

    assert result.points == ()
    assert result.cumulative_twr == Decimal("0.0000000000")


def test_is_provisional_when_any_row_in_range_is_provisional(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    db_committing.add(
        _sub_period(
            customer_id,
            start=TODAY - timedelta(days=10),
            end=TODAY,
            return_pct=Decimal("0.0000000000"),
            value_begin=Money("10000.0000"),
            value_end=Money("10000.0000"),
            is_provisional=True,
        )
    )
    db_committing.commit()

    result = _performance(customer_id, performance_range="1m")

    assert result.is_provisional is True


def test_another_customers_rows_are_never_included(db_committing: Session) -> None:
    customer_id = _seed_customer(db_committing)
    other_customer_id = _seed_customer(db_committing)
    db_committing.add(
        _sub_period(
            other_customer_id,
            start=TODAY - timedelta(days=10),
            end=TODAY,
            return_pct=Decimal("0.9900000000"),
            value_begin=Money("1.0000"),
            value_end=Money("199.0000"),
        )
    )
    db_committing.commit()

    result = _performance(customer_id, performance_range="all")

    assert result.points == ()
    assert result.cumulative_twr == Decimal("0.0000000000")
