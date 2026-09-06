"""The 8 curated read-model views S11 §4.1 defines, and the one shared allow-list ADR 19 requires:
`CURATED_VIEW_NAMES` is imported by both this migration's SQL and
`app.services.chat.sql_tool_validator` (ADR 19 §4.3 point 4 — "the same allow-list ... imported by
both, so they cannot silently diverge").

**Why these views are owner-executed with an inline tenant predicate, not `security_invoker =
true`.** ADR 19's literal SQL sketch pairs `security_invoker = true` with a `chat_readonly` role
granted `SELECT` on the 8 views "and nothing else." Postgres's actual `security_invoker` semantics
make that combination impossible: with `security_invoker = true`, the *invoking* role's own grants
are checked against the view's underlying base relations, not the owner's (`CREATE VIEW` docs,
§security_invoker) — so `chat_readonly` would need a direct `GRANT SELECT` on `posting`,
`journal_entry`, and `tax_lot` merely for the views to execute, which both contradicts "nothing
else" and means `chat_readonly` really could `SELECT * FROM posting` directly (RLS would still
scope it, but the decisive "permission denied at the DB level" test — ADR 19 §4.3, S11 §7.2 — could
never pass). Each view below is instead owner-executed (the Postgres default — no
`security_invoker` clause) with the *same* tenant predicate every `tenant_isolation` RLS policy in
this codebase already uses, inlined directly into the view body: `current_setting('app.role',
true) IN ('adviser', 'admin') OR <col> = NULLIF(current_setting('app.customer_id', true),
'')::uuid`. This reads the identical session-scoped GUCs `UnitOfWork` already sets for every other
customer-scoped request (S0 §7.3) — the enforcement point moves from "Postgres re-evaluates RLS as
the invoker" to "the view's own predicate evaluates the same GUCs," but the security property is
identical: `chat_readonly` has zero grants on any raw relation (satisfying FR-50's literal
requirement), and cross-tenant access is refused by the database itself, independent of the LLM,
the validator, or application code (ADR 19's one governing sentence). Escalated to `main` before
this file was written; flagged here so the reasoning travels with the code, not only the PR.

`as_of` is not a view parameter (Postgres views cannot take one) — each view that "accepts `as_of`"
per S11 §4.1 instead exposes its own temporal column (`recorded_at`, `sale_date`, or
`publish_watermark`) directly, so a live read is an unfiltered/latest-row query and an as-published
read is an ordinary `WHERE <temporal column> <= :watermark` the validator already permits as plain
SQL — no parameterized function, and no new allow-listed function, needed.

`v_holdings` is **live only**: `tax_lot` is a mutable-in-place projection (S5's own docstring), not
a bitemporal/append-only table, so there is no existing mechanism to reconstruct "holdings as of a
past date" from it — and S11 §4.1 itself is explicit that this spec "adds no new temporal logic, it
only exposes the existing mechanism through a narrower, LLM-safe surface." An as-published holdings
question is answered from `v_published_snapshot.holdings_json` instead, which already carries a
point-in-time holdings snapshot (S6 §3.1) — the system prompt directs the agent there.
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

CREATE_CURATED_VIEWS_SQL = """
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
""".format(
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
