"""The only code that opens a DB connection under `DbRole.CHAT`; enforces timeout + row cap (ADR 19 §4.2/§4.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import psycopg
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.db import DbRole
from app.core.logging import get_logger
from app.core.uow import SessionRole, UnitOfWork
from app.integrations.openai.llm_agent_port import SqlToolOutcome
from app.models.chat.curated_views import CURATED_VIEW_NAMES
from app.services.chat.sql_tool_validator import validate_query

if TYPE_CHECKING:
    import uuid

log = get_logger(__name__)


def _stringify(value: object) -> str:
    return "" if value is None else str(value)


class ReadOnlySqlExecutor:
    def __init__(self, *, statement_timeout_ms: int = 3000, row_cap: int = 1000) -> None:
        if statement_timeout_ms <= 0 or row_cap <= 0:
            raise ValueError("statement_timeout_ms and row_cap must be positive")
        self._statement_timeout_ms = statement_timeout_ms
        self._row_cap = row_cap

    def describe_schema(self, customer_id: uuid.UUID) -> str:
        """`get_database_schema` (S11 §3) -- reads live curated-view column metadata."""
        with UnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.CHAT
        ) as uow:
            rows = uow.session.execute(
                text(
                    "SELECT table_name, column_name FROM information_schema.columns "
                    "WHERE table_name = ANY(:names) ORDER BY table_name, ordinal_position"
                ),
                {"names": sorted(CURATED_VIEW_NAMES)},
            ).all()

        columns_by_view: dict[str, list[str]] = {}
        for table_name, column_name in rows:
            columns_by_view.setdefault(table_name, []).append(column_name)
        return "\n".join(
            f"{view}({', '.join(columns)})" for view, columns in sorted(columns_by_view.items())
        )

    def execute(self, sql: str, *, customer_id: uuid.UUID) -> SqlToolOutcome:
        """`execute_read_only_sql` (S11 §3). Validates first (ADR 19 §4.3)."""
        validation = validate_query(sql)
        if not validation.ok or validation.normalized_sql is None:
            return SqlToolOutcome(
                status="validator_rejected", message=validation.reason or "query rejected"
            )

        # Not a bind param: normalized_sql is parser-validated per ADR 19 §4.3.
        wrapped_sql = (
            f"SELECT * FROM ({validation.normalized_sql}) AS sub LIMIT {self._row_cap}"  # noqa: S608 # nosec B608
        )
        try:
            with UnitOfWork(
                customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.CHAT
            ) as uow:
                uow.session.execute(
                    text(f"SET LOCAL statement_timeout = '{self._statement_timeout_ms}ms'")
                )
                mappings = uow.session.execute(text(wrapped_sql)).mappings().all()
        except SQLAlchemyError as exc:
            if isinstance(getattr(exc, "orig", None), psycopg.errors.QueryCanceled):
                return SqlToolOutcome(
                    status="timeout", message="the query took too long and was cancelled"
                )
            log.warning("chat_sql_execution_failed", exc_info=exc)
            return SqlToolOutcome(status="error", message="the query could not be executed")

        rows = tuple(
            {key: _stringify(value) for key, value in mapping.items()} for mapping in mappings
        )
        return SqlToolOutcome(status="success", rows=rows, row_count=len(rows))


__all__ = ["ReadOnlySqlExecutor"]
