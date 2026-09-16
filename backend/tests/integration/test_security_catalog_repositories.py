"""`SecurityRepository.list_active`/`DailyCloseRepository.latest_for_securities` against real
Postgres (backing `GET /api/v1/securities`): the `status` filter, keyset pagination, and the
`market_date`-before-`recorded_at` ordering rule for "latest close" -- a late correction to an old
date must never look newer than a genuinely newer close.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import event, text

from app.core.db import DbRole
from app.core.money import Price
from app.core.uow import SessionRole
from app.models.marketdata import MarketDataUnitOfWork
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass, SecurityStatus

CATALOG_TABLES = [Security.__table__, DailyClose.__table__]


@pytest.fixture(autouse=True)
def _catalog_tables(owner_engine) -> Iterator[None]:
    for table in CATALOG_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(CATALOG_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _owner_uow() -> MarketDataUnitOfWork:
    return MarketDataUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _insert_security(
    uow: MarketDataUnitOfWork, *, symbol: str, status: SecurityStatus = SecurityStatus.ACTIVE
) -> Security:
    security = Security(
        symbol=symbol, name=f"{symbol} Co", asset_class=SecurityAssetClass.EQUITY, status=status
    )
    uow.session.add(security)
    uow.session.flush()
    return security


def _insert_close(
    uow: MarketDataUnitOfWork,
    *,
    security_id: uuid.UUID,
    market_date: date,
    recorded_at: datetime,
    price: str = "100.00",
    source: MarketDataSource = MarketDataSource.LIVE,
    status: DailyCloseStatus = DailyCloseStatus.CONFIRMED,
) -> DailyClose:
    close = DailyClose(
        security_id=security_id,
        market_date=market_date,
        close_price=Price(price),
        source=source,
        status=status,
        recorded_at=recorded_at,
    )
    uow.session.add(close)
    uow.session.flush()
    return close


@contextmanager
def _query_counter(uow: MarketDataUnitOfWork) -> Iterator[list[int]]:
    """Yields a one-element list holding the number of statements executed against `uow`'s
    connection while the `with` block is open -- mutable so the caller can read it after."""
    engine = uow.session.get_bind()
    counts = [0]

    def _increment(*_args: object, **_kwargs: object) -> None:
        counts[0] += 1

    event.listen(engine, "before_cursor_execute", _increment)
    try:
        yield counts
    finally:
        event.remove(engine, "before_cursor_execute", _increment)


# --- list_active: status filter + keyset pagination -------------------------------------------


def test_list_active_filters_status_and_paginates_by_keyset() -> None:
    with _owner_uow() as uow:
        aaa = _insert_security(uow, symbol="AAA")
        _insert_security(uow, symbol="BBB", status=SecurityStatus.INACTIVE)
        ccc = _insert_security(uow, symbol="CCC")
        ddd = _insert_security(uow, symbol="DDD")
        eee = _insert_security(uow, symbol="EEE")

        first_page = uow.securities.list_active(limit=2, after=None)

        # limit + 1 rows: proves a further page exists, and the inactive row never appears.
        assert [s.symbol for s in first_page] == ["AAA", "CCC", "DDD"]
        assert aaa.id in {s.id for s in first_page}

        second_page = uow.securities.list_active(limit=2, after=(ccc.symbol, ccc.id))

        # Picks up exactly where the first page left off -- DDD, EEE, no inactive BBB anywhere.
        assert [s.symbol for s in second_page] == ["DDD", "EEE"]
        assert {s.id for s in second_page} == {ddd.id, eee.id}


# --- latest_for_securities: market_date beats recorded_at --------------------------------------


def test_latest_for_securities_prefers_newer_market_date_over_newer_recorded_at() -> None:
    with _owner_uow() as uow:
        security = _insert_security(uow, symbol="AAA")
        # Older market_date, but recorded very recently.
        _insert_close(
            uow,
            security_id=security.id,
            market_date=date(2026, 1, 5),
            recorded_at=datetime(2026, 1, 7, 12, 0, tzinfo=UTC),
            price="100.00",
        )
        # Newer market_date, recorded earlier -- this is the true "latest" close.
        newer_date_close = _insert_close(
            uow,
            security_id=security.id,
            market_date=date(2026, 1, 6),
            recorded_at=datetime(2026, 1, 5, 9, 0, tzinfo=UTC),
            price="101.00",
        )

        result = uow.daily_closes.latest_for_securities([security.id])

        assert result[security.id].id == newer_date_close.id
        assert result[security.id].close_price == Price("101.00")


def test_latest_for_securities_prefers_late_correction_on_the_same_market_date() -> None:
    with _owner_uow() as uow:
        security = _insert_security(uow, symbol="AAA")
        _insert_close(
            uow,
            security_id=security.id,
            market_date=date(2026, 1, 10),
            recorded_at=datetime(2026, 1, 10, 16, 0, tzinfo=UTC),
            price="100.00",
        )
        # A late-arriving correction to the same market_date -- newer recorded_at wins here,
        # since market_date is tied.
        correction = _insert_close(
            uow,
            security_id=security.id,
            market_date=date(2026, 1, 10),
            recorded_at=datetime(2026, 1, 11, 9, 0, tzinfo=UTC),
            price="105.00",
        )

        result = uow.daily_closes.latest_for_securities([security.id])

        assert result[security.id].id == correction.id
        assert result[security.id].close_price == Price("105.00")


def test_latest_for_securities_returns_empty_dict_for_empty_input() -> None:
    with _owner_uow() as uow:
        assert uow.daily_closes.latest_for_securities([]) == {}


def test_latest_for_securities_issues_exactly_one_query_for_many_securities() -> None:
    with _owner_uow() as uow:
        securities = [_insert_security(uow, symbol=f"SYM{i}") for i in range(5)]
        for security in securities:
            _insert_close(
                uow,
                security_id=security.id,
                market_date=date(2026, 1, 10),
                recorded_at=datetime(2026, 1, 10, 16, 0, tzinfo=UTC),
            )

        with _query_counter(uow) as counts:
            result = uow.daily_closes.latest_for_securities([s.id for s in securities])

        assert counts[0] == 1
        assert set(result.keys()) == {s.id for s in securities}
