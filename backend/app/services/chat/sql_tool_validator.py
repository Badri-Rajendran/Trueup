"""Static query-shape check before `execute_read_only_sql` opens a connection (S11 §4.3, ADR 19).

Pure function: parses with `sqlglot`, rejects multi-statement/non-SELECT/uncurated
relations/disallowed functions, and returns the re-serialized SQL on success.
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
