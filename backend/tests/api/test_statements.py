"""`GET /api/v1/statements` (S6 §8, FR-25/26) via the Flask test client: happy path, authn, and
cursor pagination (S12 §8) -- `limit`/`cursor` validation and a no-duplicate/no-skip page walk.
`GET /<period>` and `/<period>/export` are covered by `test_statements_export.py`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.money import Money
from app.models.restatement.published_snapshot import PublishedSnapshot

CUSTOMER_EMAIL = "statements-customer@trueup.example"
OTHER_EMAIL = "statements-other@trueup.example"
PASSWORD = "correct-horse-battery"

STATEMENTS_TABLES = [PublishedSnapshot.__table__]


@pytest.fixture(autouse=True)
def _statements_tables(owner_engine: Engine) -> Iterator[None]:
    for table in STATEMENTS_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(STATEMENTS_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _register_and_login(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL
) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _publish_snapshot(
    owner_engine: Engine,
    customer_id: uuid.UUID,
    *,
    period_start: date,
    period_end: date,
    publish_watermark: datetime | None = None,
    snapshot_id: uuid.UUID | None = None,
) -> uuid.UUID:
    watermark = (
        publish_watermark
        if publish_watermark is not None
        else datetime(period_end.year, period_end.month, 28, tzinfo=UTC)
    )
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        snapshot = PublishedSnapshot(
            id=snapshot_id if snapshot_id is not None else uuid.uuid4(),
            customer_id=customer_id,
            period_start=period_start,
            period_end=period_end,
            publish_watermark=watermark,
            twr=Decimal("0.0100000000"),
            balance=Money("5000.00"),
            holdings_json={},
            published_at=watermark,
        )
        session.add(snapshot)
        session.commit()
        return snapshot.id
    finally:
        session.close()


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/statements")

    assert response.status_code == 401


def test_lists_published_statements_newest_period_first(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    _publish_snapshot(
        owner_engine, uuid.UUID(customer_id),
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    _publish_snapshot(
        owner_engine, uuid.UUID(customer_id),
        period_start=date(2026, 2, 1), period_end=date(2026, 2, 28),
    )

    response = api_client.get("/api/v1/statements")

    assert response.status_code == 200
    body = response.get_json()
    assert [s["period_start"] for s in body["statements"]] == ["2026-02-01", "2026-01-01"]
    assert body["next_cursor"] is None


def test_a_republished_period_orders_by_newest_publish_watermark_first(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    """FR-26: `period_start` is not unique per customer -- a period can be republished under
    several watermarks, and `latest_for_period` orders those by `publish_watermark DESC`
    specifically to mean "most recent republish first". The pagination cursor key must preserve
    that same order rather than falling back to `id` (unrelated to republish recency): the older
    republish is given the numerically LARGER `id` and is inserted FIRST here, so an
    implementation that (incorrectly) tiebreaks on `id` would order it first -- the wrong answer
    -- rather than this test passing by insertion-order or id-magnitude coincidence."""
    customer_id, _ = _register_and_login(api_client)
    older_watermark = datetime(2026, 2, 1, tzinfo=UTC)
    newer_watermark = datetime(2026, 3, 1, tzinfo=UTC)
    _publish_snapshot(
        owner_engine, uuid.UUID(customer_id),
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        publish_watermark=older_watermark, snapshot_id=uuid.UUID(int=2**128 - 1),
    )
    _publish_snapshot(
        owner_engine, uuid.UUID(customer_id),
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
        publish_watermark=newer_watermark, snapshot_id=uuid.UUID(int=0),
    )

    response = api_client.get("/api/v1/statements")

    assert response.status_code == 200
    body = response.get_json()
    assert len(body["statements"]) == 2
    watermarks = [datetime.fromisoformat(s["publish_watermark"]) for s in body["statements"]]
    assert watermarks == [newer_watermark, older_watermark]


def test_a_customer_never_sees_another_customers_statements(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    _publish_snapshot(
        owner_engine, uuid.UUID(other_id),
        period_start=date(2026, 1, 1), period_end=date(2026, 1, 31),
    )
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _register_and_login(api_client)

    response = api_client.get("/api/v1/statements")

    assert response.status_code == 200
    assert response.get_json() == {"statements": [], "next_cursor": None}


# --- pagination (S12 §8) -------------------------------------------------------------------------


def test_rejects_limit_over_max(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    response = api_client.get("/api/v1/statements?limit=201")

    assert response.status_code == 422


def test_rejects_a_malformed_cursor(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    response = api_client.get("/api/v1/statements?cursor=not-a-real-cursor")

    assert response.status_code == 422


def test_pages_through_with_no_duplicate_or_skip(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id, _ = _register_and_login(api_client)
    for month in (1, 2, 3):
        _publish_snapshot(
            owner_engine, uuid.UUID(customer_id),
            period_start=date(2026, month, 1), period_end=date(2026, month, 28),
        )

    full = api_client.get("/api/v1/statements").get_json()
    assert len(full["statements"]) == 3
    assert full["next_cursor"] is None

    first_page = api_client.get("/api/v1/statements?limit=2").get_json()
    assert first_page["statements"] == full["statements"][:2]
    assert first_page["next_cursor"] is not None

    second_page = api_client.get(
        f"/api/v1/statements?limit=2&cursor={first_page['next_cursor']}"
    ).get_json()
    assert second_page["statements"] == full["statements"][2:]
    assert second_page["next_cursor"] is None


def test_is_throttled(api_client: FlaskClient) -> None:
    _register_and_login(api_client)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/statements")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
