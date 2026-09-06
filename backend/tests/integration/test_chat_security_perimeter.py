"""ADR 19's decisive proofs, run against the real curated views and the real `chat_readonly`
role -- never a mock, since the whole point of this ADR is that the boundary is the database
itself (S11 §7.2).

1. A curated view's own tenant predicate actually applies: querying it as customer A returns only
   customer A's rows, and customer B's row is structurally absent -- not merely unrequested.
2. `chat_readonly` gets a database-level permission-denied error on `posting`/`bank_link`/
   `admin_audit_log`, never a filtered/empty result -- proving the zero-grant role, independent
   of RLS or the validator.
3. A deliberately slow query is actually cancelled by the per-query statement timeout.

Self-sufficient table/view setup, matching `tests/integration/conftest.py::ledger_tables`'s own
precedent (nothing in this project runs Alembic against the test database).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.models.chat.curated_views import (
    CREATE_CURATED_VIEWS_SQL,
    CURATED_VIEW_NAMES,
    DROP_CURATED_VIEWS_SQL,
    GRANT_CURATED_VIEWS_SQL,
)
from app.models.identity.bank_link import BankLink
from app.models.identity.customer import Customer
from app.models.ledger.account import Account
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.posting import Posting
from app.models.ledger.tax_lot import TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.ops.admin_audit_log import AdminAuditLog
from app.models.ops.inbound_event import InboundEvent
from app.models.orders.order import Order
from app.models.orders.order_event import OrderEvent
from app.models.restatement.published_snapshot import PublishedSnapshot
from app.services.chat.read_only_sql_executor import ReadOnlySqlExecutor

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.engine import Connection

# Dependency order: every table every one of the 8 curated views reads from, plus the two named
# "never" tables (bank_link, admin_audit_log) -- the full set `CREATE_CURATED_VIEWS_SQL` needs to
# succeed as one batch, mirroring what the real migration builds on top of.
_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    Security.__table__,
    Order.__table__,
    OrderEvent.__table__,
    TaxLot.__table__,
    LotConsumption.__table__,
    WashSaleAdjustment.__table__,
    SubPeriodReturn.__table__,
    PublishedSnapshot.__table__,
    BankLink.__table__,
    AdminAuditLog.__table__,
]


@pytest.fixture
def chat_perimeter(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    with owner_engine.begin() as connection:
        connection.execute(text(CREATE_CURATED_VIEWS_SQL))
        connection.execute(text(GRANT_CURATED_VIEWS_SQL))
    yield
    with owner_engine.begin() as connection:
        connection.execute(text(DROP_CURATED_VIEWS_SQL))
    for table in reversed(_TABLES):
        table.drop(bind=owner_engine, checkfirst=True)


def _insert_customer(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO customer (id, email, password_hash, kyc_status, "
                "account_approval_status) VALUES (:id, :email, 'x', 'approved', 'approved')"
            ),
            {"id": customer_id, "email": f"{customer_id}@test.trueup"},
        )


def _insert_sub_period_return(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO sub_period_return (id, customer_id, sub_period_start, "
                "sub_period_end, return_pct, value_begin, value_end, flow_amount, "
                "is_provisional, recorded_at) VALUES (:id, :customer_id, '2026-01-01', "
                "'2026-01-31', 0.0100000000, 100.0000, 101.0000, 0.0000, false, :now)"
            ),
            {"id": uuid.uuid4(), "customer_id": customer_id, "now": datetime.now(UTC)},
        )


def _insert_many_sub_period_returns(
    owner_engine: Engine, customer_id: uuid.UUID, count: int
) -> None:
    """Enough distinct rows that a 3-way self cross-join over `v_period_return` takes real,
    measurable time (`count ** 3` combinations) -- used to force a genuinely slow query through
    `ReadOnlySqlExecutor`'s own timeout, rather than a `pg_sleep` the validator would reject."""
    with owner_engine.begin() as connection:
        for offset in range(count):
            connection.execute(
                text(
                    "INSERT INTO sub_period_return (id, customer_id, sub_period_start, "
                    "sub_period_end, return_pct, value_begin, value_end, flow_amount, "
                    "is_provisional, recorded_at) VALUES (:id, :customer_id, "
                    "(DATE '2020-01-01' + :offset), (DATE '2020-01-01' + :offset + 1), "
                    "0.0100000000, 100.0000, 101.0000, 0.0000, false, :now)"
                ),
                {
                    "id": uuid.uuid4(),
                    "customer_id": customer_id,
                    "offset": offset,
                    "now": datetime.now(UTC),
                },
            )


def _set_chat_session(connection: Connection, *, customer_id: uuid.UUID | None) -> None:
    connection.execute(text("SELECT set_config('app.role', 'customer', false)"))
    connection.execute(
        text("SELECT set_config('app.customer_id', :customer_id, false)"),
        {"customer_id": str(customer_id) if customer_id else ""},
    )


def test_curated_view_enforces_tenant_isolation(
    owner_engine: Engine, chat_engine: Engine, chat_perimeter: None
) -> None:
    """ADR 19's decisive test: query `v_period_return` as customer A and assert customer B's row
    is structurally absent -- not merely unrequested."""
    customer_a, customer_b = uuid.uuid4(), uuid.uuid4()
    _insert_customer(owner_engine, customer_a)
    _insert_customer(owner_engine, customer_b)
    _insert_sub_period_return(owner_engine, customer_a)
    _insert_sub_period_return(owner_engine, customer_b)

    with chat_engine.begin() as connection:
        _set_chat_session(connection, customer_id=customer_a)
        rows = connection.execute(text("SELECT customer_id FROM v_period_return")).all()

    assert [row.customer_id for row in rows] == [customer_a]
    assert customer_b not in [row.customer_id for row in rows]


@pytest.mark.parametrize("table_name", ["posting", "bank_link", "admin_audit_log"])
def test_chat_readonly_cannot_select_raw_tables(
    chat_engine: Engine, chat_perimeter: None, table_name: str
) -> None:
    """`chat_readonly` has no grant on any raw table -- a permission-denied error at the database
    itself, never an empty/filtered result (ADR 19 §4.2, S11 §7.2)."""
    with pytest.raises(DBAPIError) as exc_info, chat_engine.begin() as connection:
        connection.execute(text(f"SELECT * FROM {table_name}"))  # noqa: S608 - fixed allow-list, test-only
    assert "permission denied" in str(exc_info.value).lower()


def test_statement_timeout_cancels_a_slow_query(chat_engine: Engine, chat_perimeter: None) -> None:
    """The generic Postgres mechanism `ReadOnlySqlExecutor` relies on: a statement timeout really
    does cancel a running query (ADR 19 §4.4). `test_read_only_sql_executor_times_out_a_slow_query`
    below is the decisive test that this actually fires through the executor's own code path --
    this one only proves the underlying database behavior exists to rely on."""
    with pytest.raises(DBAPIError) as exc_info, chat_engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '200ms'"))
        connection.execute(text("SELECT pg_sleep(2)"))
    assert "statement timeout" in str(exc_info.value).lower()


def test_read_only_sql_executor_times_out_a_slow_query(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """The decisive test for ADR 19 §4.4: calls `ReadOnlySqlExecutor.execute()` itself -- the real
    production code path `ChatOrchestrationService` drives -- with a query that is slow because it
    does real, validator-legal work (a 3-way self cross-join over `v_period_return`, aggregated
    with the allow-listed `count`), not a `pg_sleep` the validator would reject outright.
    """
    customer_id = uuid.uuid4()
    _insert_customer(owner_engine, customer_id)
    _insert_many_sub_period_returns(owner_engine, customer_id, count=300)

    executor = ReadOnlySqlExecutor(statement_timeout_ms=200)
    outcome = executor.execute(
        "SELECT count(*) FROM v_period_return a, v_period_return b, v_period_return c",
        customer_id=customer_id,
    )

    assert outcome.status == "timeout"
    assert outcome.row_count == 0


def test_curated_views_match_the_shared_allow_list(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """ADR 19 §4.3's "one shared allow-list" guarantee is only real if something actually checks
    the migration's `CREATE_CURATED_VIEWS_SQL` produces exactly `CURATED_VIEW_NAMES` -- the two are
    hand-written independently today, and nothing else would catch one drifting from the other."""
    with owner_engine.begin() as connection:
        rows = connection.execute(
            text("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")
        ).all()

    assert {row.table_name for row in rows} == CURATED_VIEW_NAMES
