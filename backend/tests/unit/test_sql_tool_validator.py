"""`sql_tool_validator`: adversarial queries (multi-statement, DDL/DML, off-allow-list, disallowed
functions) rejected, valid queries pass unchanged (ADR 19 §4.3, S11 §7.1)."""

from __future__ import annotations

import pytest

from app.services.chat.sql_tool_validator import validate_query

_ADVERSARIAL_QUERIES = [
    ("SELECT * FROM v_holdings; SELECT * FROM v_holdings", "multiple statements"),
    ("SELECT * FROM v_holdings; DROP TABLE posting;", "trailing semicolon plus DDL"),
    ("DROP TABLE posting", "DDL keyword"),
    ("DELETE FROM v_holdings", "DML keyword"),
    ("UPDATE v_holdings SET quantity_remaining = 0", "DML keyword"),
    ("INSERT INTO v_holdings DEFAULT VALUES", "DML keyword"),
    ("SELECT * FROM posting", "off-allow-list relation"),
    ("SELECT * FROM bank_link", "off-allow-list relation"),
    ("SELECT * FROM admin_audit_log", "off-allow-list relation"),
    ("WITH x AS (SELECT * FROM posting) SELECT * FROM x", "off-allow-list relation via CTE"),
    (
        "SELECT * FROM v_holdings UNION SELECT * FROM posting",
        "off-allow-list relation via set operation",
    ),
    ("SELECT pg_sleep(5) FROM v_holdings", "disallowed function pg_sleep"),
    ("SELECT dblink('x', 'y') FROM v_holdings", "disallowed function dblink"),
    ("SELECT * FROM v_holdings /* trick */; SELECT 1", "comment-obfuscated multiple statements"),
    ("not even valid sql (((", "unparseable input"),
    ("", "empty input"),
    (
        "SELECT * FROM v_holdings WHERE quantity_remaining > 0 AND pg_sleep(1) IS NULL",
        "disallowed function nested inside an AND -- the Connector skip must not become a bypass",
    ),
    ("SELECT try_cast(symbol AS int) FROM v_holdings", "disallowed function try_cast"),
    ("SELECT holdings_json -> 'x' FROM v_published_snapshot", "disallowed json-extract operator"),
    ("SELECT value_end ^ 2 FROM v_period_return", "disallowed power operator"),
    ("SELECT symbol FROM v_holdings WHERE symbol ~ 'A'", "disallowed regexp-match operator"),
]

_VALID_QUERIES = [
    "SELECT * FROM v_holdings",
    "SELECT * FROM v_holdings;",
    "SELECT customer_id, quantity_remaining FROM v_holdings WHERE quantity_remaining > 0",
    "SELECT sum(amount_money) FROM v_customer_balance WHERE recorded_at <= now()",
    "SELECT count(*) FROM v_transaction_history",
    "WITH recent AS (SELECT * FROM v_transaction_history) SELECT * FROM recent",
    "SELECT * FROM v_period_return WHERE recorded_at <= current_timestamp",
    (
        "SELECT sale_date, sum(realized_gain_loss) FROM v_realized_gains "
        "GROUP BY sale_date ORDER BY sale_date"
    ),
    (
        "SELECT symbol, quantity_remaining FROM v_holdings "
        "WHERE quantity_remaining > 0 AND symbol = 'AAPL'"
    ),
    (
        "SELECT sub_period_start, return_pct FROM v_period_return "
        "WHERE sub_period_start >= date_trunc('month', current_date) AND is_provisional = false"
    ),
    "SELECT * FROM v_dividends WHERE effective_date >= '2026-01-01' OR account_role = 'cash'",
    (
        "SELECT symbol FROM v_tax_lots WHERE designation = 'long' "
        "AND (quantity_remaining > 0 OR quantity_opened > 0)"
    ),
    (
        "SELECT symbol FROM v_holdings WHERE symbol LIKE 'A%' "
        "AND acquired_at BETWEEN '2020-01-01' AND '2021-01-01'"
    ),
    "SELECT symbol FROM v_holdings WHERE NOT (symbol = 'A' AND quantity_remaining > 0)",
]


@pytest.mark.parametrize(("sql", "reason"), _ADVERSARIAL_QUERIES)
def test_rejects_adversarial_queries(sql: str, reason: str) -> None:
    result = validate_query(sql)
    assert result.ok is False, f"expected rejection ({reason}) for: {sql!r}"
    assert result.reason
    assert result.normalized_sql is None


@pytest.mark.parametrize("sql", _VALID_QUERIES)
def test_accepts_valid_queries(sql: str) -> None:
    result = validate_query(sql)
    assert result.ok is True, f"expected acceptance for: {sql!r}, got: {result.reason}"
    assert result.normalized_sql is not None
    assert result.reason is None


def test_normalized_sql_drops_comments() -> None:
    """The executed text is re-serialized, never the raw input, so comment-obfuscation fails."""
    result = validate_query("SELECT * FROM v_holdings /* sneaky comment */")
    assert result.ok is True
    assert result.normalized_sql is not None
    assert "sneaky" not in result.normalized_sql


def test_off_allow_list_relation_reason_names_the_available_views() -> None:
    """Observed live: the model guessed `transactions` instead of `v_transaction_history` and
    gave up on a bare rejection. The error must name the real options in the same tool result."""
    result = validate_query("SELECT * FROM transactions")
    assert result.ok is False
    assert result.reason is not None
    assert "v_transaction_history" in result.reason
    assert "v_holdings" in result.reason


def test_disallowed_function_reason_names_the_available_functions() -> None:
    result = validate_query("SELECT pg_sleep(5) FROM v_holdings")
    assert result.ok is False
    assert result.reason is not None
    assert "sum" in result.reason
    assert "count" in result.reason
