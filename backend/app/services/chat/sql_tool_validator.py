"""`sql_tool_validator` (S11 §4.3, ADR 19) — the static query-shape check run before
`execute_read_only_sql` ever opens a database connection. Pure function, no I/O: parses with a real
SQL parser (`sqlglot`, Postgres dialect) rather than string matching, which is trivially defeated by
whitespace/comment tricks (ADR 19's own reasoning).

Five checks, in order, each returning a structured rejection reason on failure (never a raw parser
exception -- `ValidationResult.reason` is always customer/agent-safe):

1. Parses at all.
2. Exactly one statement (rejects a trailing `;` followed by more SQL).
3. That statement is a `SELECT` (a plain `Select`, or a `UNION`/`INTERSECT`/`EXCEPT` of them --
   still purely read-only; every DML/DDL class fails this check at the AST level).
4. Every referenced relation is in `CURATED_VIEW_NAMES` -- the **same** allow-list constant
   `curated_views.py`'s migration SQL grants `chat_readonly`, imported from one place so the two
   cannot silently diverge (ADR 19 §4.3 point 4). A CTE's own alias is excluded from this check --
   it names a local result set, not a relation to authorize.
5. Every function call is on `_ALLOWED_FUNCTIONS` (aggregate/date functions only) -- closes off
   `pg_sleep`, `dblink`, and anything else with no legitimate role in a reporting query.

On success, `ValidationResult.normalized_sql` is the **re-serialized** statement, not the caller's
original text -- comments are dropped and formatting is canonicalized in the process, which is a
second, incidental defense against a comment-based obfuscation trick surviving into what actually
executes. `ChatOrchestrationService` executes `normalized_sql`, never the raw input.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlglot
from sqlglot import exp

from app.models.chat.curated_views import CURATED_VIEW_NAMES

_ALLOWED_FUNCTIONS: frozenset[str] = frozenset(
    {
        "sum",
        "count",
        "avg",
        "min",
        "max",
        "coalesce",
        "nullif",
        "cast",
        "abs",
        "round",
        "extract",
        "date_trunc",
        "timestamp_trunc",
        "current_timestamp",
        "current_date",
    }
)

_ALLOWED_STATEMENT_TYPES: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    normalized_sql: str | None = None
    reason: str | None = None


def validate_query(sql: str) -> ValidationResult:
    try:
        parsed = sqlglot.parse(sql, dialect="postgres")
        statements = [statement for statement in parsed if statement is not None]
    except sqlglot.errors.SqlglotError:
        return ValidationResult(ok=False, reason="the query could not be parsed as SQL")

    if len(statements) == 0:
        return ValidationResult(ok=False, reason="no SQL statement was found")
    if len(statements) > 1:
        return ValidationResult(ok=False, reason="only a single SQL statement is allowed")

    statement = statements[0]
    if not isinstance(statement, _ALLOWED_STATEMENT_TYPES):
        return ValidationResult(ok=False, reason="only a SELECT statement is allowed")

    cte_names = {cte.alias_or_name.lower() for cte in statement.find_all(exp.CTE)}
    for table in statement.find_all(exp.Table):
        name = table.name.lower()
        if name in cte_names:
            continue
        if name not in CURATED_VIEW_NAMES:
            return ValidationResult(
                ok=False, reason=f"relation '{table.name}' is not available to this assistant"
            )

    for func in statement.find_all(exp.Func):
        name = func.name.lower() if isinstance(func, exp.Anonymous) else func.sql_name().lower()
        if name not in _ALLOWED_FUNCTIONS:
            return ValidationResult(
                ok=False, reason=f"function '{name}' is not available to this assistant"
            )

    return ValidationResult(
        ok=True, normalized_sql=statement.sql(dialect="postgres", comments=False)
    )


__all__ = ["ValidationResult", "validate_query"]
