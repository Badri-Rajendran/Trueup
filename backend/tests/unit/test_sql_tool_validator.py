"""`sql_tool_validator` (ADR 19 §4.3) against an adversarial table: multiple statements, a
trailing semicolon plus more SQL, write/DDL keywords, disallowed functions, off-allow-list
relations -- and a table of valid queries that must pass unchanged (S11 §7.1).
"""

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
    """A second, incidental defense: the executed text is re-serialized, never the raw input, so
    a comment-based obfuscation trick cannot survive into what actually runs (ADR 19 §4.3)."""
    result = validate_query("SELECT * FROM v_holdings /* sneaky comment */")
    assert result.ok is True
    assert result.normalized_sql is not None
    assert "sneaky" not in result.normalized_sql
