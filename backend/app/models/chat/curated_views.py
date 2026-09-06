"""The 8 curated read-model views (S11 §4.1) and shared allow-list (ADR 19).

Owner-executed with an inlined tenant predicate rather than `security_invoker = true` (ADR 19 §4.3,
S11 §7.2). `v_holdings` is live-only; as-published holdings come from `v_published_snapshot`.
"""

from __future__ import annotations

CURATED_VIEW_NAMES: frozenset[str] = frozenset(
    {
        "v_customer_balance",
        "v_holdings",
        "v_transaction_history",
        "v_realized_gains",
        "v_tax_lots",
        "v_dividends",
        "v_period_return",
        "v_published_snapshot",
    }
)

_TENANT_PREDICATE = (
    "current_setting('app.role', true) IN ('adviser', 'admin') "
    "OR {column} = NULLIF(current_setting('app.customer_id', true), '')::uuid"
)

_CURATED_VIEWS_SQL_TEMPLATE = """
CREATE OR REPLACE VIEW v_customer_balance AS
SELECT
    a.customer_id,
    p.id AS posting_id,
    je.recorded_at,
    p.amount_money
FROM posting p
JOIN account a ON a.id = p.account_id
JOIN journal_entry je ON je.id = p.journal_entry_id
WHERE a.role = 'cash'
  AND je.superseded_by IS NULL
  AND ({tenant_a});

CREATE OR REPLACE VIEW v_holdings AS
SELECT
    tl.customer_id,
    tl.security_id,
    s.symbol,
    s.name AS security_name,
    tl.quantity_remaining,
    tl.original_cost_basis,
    tl.adjusted_basis,
    tl.acquired_at
FROM tax_lot tl
JOIN security s ON s.id = tl.security_id
WHERE tl.quantity_remaining > 0
  AND ({tenant_tl});

CREATE OR REPLACE VIEW v_transaction_history AS
SELECT
    p.customer_id,
    je.id AS journal_entry_id,
    je.entry_type,
    je.effective_date,
    je.recorded_at,
    je.memo,
    p.amount_money,
    p.quantity_units,
    a.role AS account_role,
    a.security_id
FROM posting p
JOIN journal_entry je ON je.id = p.journal_entry_id
JOIN account a ON a.id = p.account_id
WHERE je.superseded_by IS NULL
  AND ({tenant_p});

CREATE OR REPLACE VIEW v_realized_gains AS
SELECT
    tl.customer_id,
    tl.security_id,
    s.symbol,
    lc.sale_date,
    lc.quantity_consumed,
    lc.realized_gain_loss,
    lc.is_provisional,
    COALESCE(wsa.disallowed_amount, 0) AS wash_sale_disallowed_amount
FROM lot_consumption lc
JOIN tax_lot tl ON tl.id = lc.tax_lot_id
JOIN security s ON s.id = tl.security_id
LEFT JOIN wash_sale_adjustment wsa ON wsa.original_lot_consumption_id = lc.id
WHERE ({tenant_tl2});

CREATE OR REPLACE VIEW v_tax_lots AS
SELECT
    tl.customer_id,
    tl.security_id,
    s.symbol,
    tl.quantity_opened,
    tl.quantity_remaining,
    tl.original_cost_basis,
    tl.adjusted_basis,
    tl.acquired_at,
    tl.designation
FROM tax_lot tl
JOIN security s ON s.id = tl.security_id
WHERE ({tenant_tl3});

CREATE OR REPLACE VIEW v_dividends AS
SELECT
    p.customer_id,
    je.id AS journal_entry_id,
    je.effective_date,
    a.security_id,
    a.role AS account_role,
    p.amount_money
FROM posting p
JOIN journal_entry je ON je.id = p.journal_entry_id
JOIN account a ON a.id = p.account_id
WHERE je.entry_type = 'dividend'
  AND je.superseded_by IS NULL
  AND ({tenant_p2});

CREATE OR REPLACE VIEW v_period_return AS
SELECT
    customer_id,
    sub_period_start,
    sub_period_end,
    return_pct,
    value_begin,
    value_end,
    flow_amount,
    is_provisional,
    recorded_at
FROM sub_period_return
WHERE ({tenant_spr});

CREATE OR REPLACE VIEW v_published_snapshot AS
SELECT
    customer_id,
    period_start,
    period_end,
    publish_watermark,
    twr,
    balance,
    holdings_json,
    published_at
FROM published_snapshot
WHERE ({tenant_ps});
"""

# Static owner-authored DDL: `.format()` substitutes only fixed column literals, never user input.
CREATE_CURATED_VIEWS_SQL = _CURATED_VIEWS_SQL_TEMPLATE.format(  # nosec B608
    tenant_a=_TENANT_PREDICATE.format(column="a.customer_id"),
    tenant_tl=_TENANT_PREDICATE.format(column="tl.customer_id"),
    tenant_p=_TENANT_PREDICATE.format(column="p.customer_id"),
    tenant_tl2=_TENANT_PREDICATE.format(column="tl.customer_id"),
    tenant_tl3=_TENANT_PREDICATE.format(column="tl.customer_id"),
    tenant_p2=_TENANT_PREDICATE.format(column="p.customer_id"),
    tenant_spr=_TENANT_PREDICATE.format(column="customer_id"),
    tenant_ps=_TENANT_PREDICATE.format(column="customer_id"),
)

DROP_CURATED_VIEWS_SQL = "\n".join(
    f"DROP VIEW IF EXISTS {name};" for name in sorted(CURATED_VIEW_NAMES)
)

GRANT_CURATED_VIEWS_SQL = (
    f"GRANT SELECT ON {', '.join(sorted(CURATED_VIEW_NAMES))} TO trueup_chat_readonly;"
)

__all__ = [
    "CREATE_CURATED_VIEWS_SQL",
    "CURATED_VIEW_NAMES",
    "DROP_CURATED_VIEWS_SQL",
    "GRANT_CURATED_VIEWS_SQL",
]
