"""ADR 19's decisive proofs against real curated views and `chat_readonly`: tenant isolation,
zero-grant permission denial, and statement-timeout cancellation (S11 §7.2)."""

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

# Every table the 8 curated views read from, plus the two "never" tables.
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
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


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
    """Enough rows that a 3-way self cross-join is genuinely slow, without a rejected `pg_sleep`."""
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
    """ADR 19: customer B's row is structurally absent when querying as customer A."""
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
    """`chat_readonly` has no grant on raw tables: DB-level permission denied (ADR 19 §4.2)."""
    with pytest.raises(DBAPIError) as exc_info, chat_engine.begin() as connection:
        connection.execute(text(f"SELECT * FROM {table_name}"))  # noqa: S608 - fixed allow-list, test-only
    assert "permission denied" in str(exc_info.value).lower()


def test_statement_timeout_cancels_a_slow_query(chat_engine: Engine, chat_perimeter: None) -> None:
    """Postgres statement_timeout cancels a running query (ADR 19 §4.4); the underlying mechanism
    `ReadOnlySqlExecutor` relies on."""
    with pytest.raises(DBAPIError) as exc_info, chat_engine.begin() as connection:
        connection.execute(text("SET LOCAL statement_timeout = '200ms'"))
        connection.execute(text("SELECT pg_sleep(2)"))
    assert "statement timeout" in str(exc_info.value).lower()


def test_read_only_sql_executor_times_out_a_slow_query(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """ADR 19 §4.4: `ReadOnlySqlExecutor.execute()` times out on a genuinely slow, validator-legal
    query (not a rejected `pg_sleep`)."""
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
    """ADR 19 §4.3: `CREATE_CURATED_VIEWS_SQL` produces exactly `CURATED_VIEW_NAMES`."""
    with owner_engine.begin() as connection:
        rows = connection.execute(
            text("SELECT table_name FROM information_schema.views WHERE table_schema = 'public'")
        ).all()

    assert {row.table_name for row in rows} == CURATED_VIEW_NAMES


def test_describe_schema_never_advertises_customer_id(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """The views bake in tenant scoping (ADR 19 §4.3); advertising `customer_id` led the model to
    invent placeholder ids that fail as UUID literals -- it is now hidden from the description."""
    customer_id = uuid.uuid4()
    _insert_customer(owner_engine, customer_id)

    schema = ReadOnlySqlExecutor().describe_schema(customer_id)
    # The scope note itself names `customer_id` deliberately (to warn the model off it) -- only
    # the per-view column listing must never contain it.
    columns_only = "\n".join(line for line in schema.splitlines() if "(" in line)

    assert "customer_id" not in columns_only
    for view in CURATED_VIEW_NAMES:
        assert f"{view}(" in schema


def test_read_only_sql_executor_runs_a_compound_where_starter_query(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """The month-to-date-return starter question, end to end: a compound WHERE now validates and
    executes against the real curated views (regression test for the `exp.Connector` skip)."""
    customer_id = uuid.uuid4()
    _insert_customer(owner_engine, customer_id)
    _insert_sub_period_return(owner_engine, customer_id)

    outcome = ReadOnlySqlExecutor().execute(
        "SELECT sub_period_start, return_pct FROM v_period_return "
        "WHERE sub_period_start >= DATE '2026-01-01' AND is_provisional = false",
        customer_id=customer_id,
    )

    assert outcome.status == "success"
    assert outcome.row_count == 1


def test_validator_rejection_is_a_structured_outcome_not_an_exception(
    owner_engine: Engine, chat_perimeter: None
) -> None:
    """S11 §5.3: a rejection comes back as a tool result the agent can act on and retry within the
    iteration cap, never as a raised error or a raw database message."""
    outcome = ReadOnlySqlExecutor().execute("SELECT * FROM posting", customer_id=uuid.uuid4())

    assert outcome.status == "validator_rejected"
    assert outcome.message
