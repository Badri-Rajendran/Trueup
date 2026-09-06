"""S13's three read tools (S13 §4.2, ADR 24). Thin translations to ADR 19's curated views'
existing `SELECT`s under `DbRole.CHAT` -- never an LLM-composed query or raw table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from mcp.server.mcpserver import (
    Context,  # noqa: TC002 -- needed at runtime for schema introspection.
)
from sqlalchemy import text

from app.core.db import DbRole
from app.core.uow import UnitOfWork
from app.mcp.auth import resolve_staff
from app.services.agent_surface.uow import AgentSurfaceUnitOfWork

_ROW_CAP = 500


def _stringify(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _parse_customer_id(customer_id: str) -> uuid.UUID:
    try:
        return uuid.UUID(customer_id)
    except ValueError as exc:
        raise ValueError(f"customer_id must be a valid UUID: {exc}") from exc


def _assigned_model(uow: AgentSurfaceUnitOfWork, customer_id: uuid.UUID) -> dict[str, Any] | None:
    assignment = uow.customer_model_assignments.get_by_customer(customer_id)
    if assignment is None:
        return None
    model = uow.model_portfolios.get_by_id(assignment.model_portfolio_id)
    return {
        "model_portfolio_id": str(assignment.model_portfolio_id),
        "name": model.name if model is not None else None,
        "assigned_at": assignment.assigned_at.isoformat(),
    }


def get_portfolio_summary(customer_id: str, ctx: Context) -> dict[str, Any]:
    """Balance, holdings, and assigned model for one customer (S13 §4.2)."""
    staff = resolve_staff(ctx.headers)
    customer_uuid = _parse_customer_id(customer_id)

    with UnitOfWork(customer_id=None, role=staff.role, db_role=DbRole.CHAT) as uow:
        balance_row = uow.session.execute(
            text(
                "SELECT COALESCE(SUM(amount_money), 0) AS balance "
                "FROM v_customer_balance WHERE customer_id = :customer_id"
            ),
            {"customer_id": customer_id},
        ).mappings().one()
        holding_rows = uow.session.execute(
            text(
                "SELECT security_id, symbol, SUM(quantity_remaining) AS quantity "
                "FROM v_holdings WHERE customer_id = :customer_id "
                "GROUP BY security_id, symbol ORDER BY symbol LIMIT :row_cap"
            ),
            {"customer_id": customer_id, "row_cap": _ROW_CAP},
        ).mappings().all()

    with AgentSurfaceUnitOfWork(customer_id=None, role=staff.role) as app_uow:
        assigned_model = _assigned_model(app_uow, customer_uuid)

    return {
        "balance": _stringify(balance_row["balance"]),
        "holdings": [
            {
                "security_id": _stringify(row["security_id"]),
                "symbol": row["symbol"],
                "quantity": _stringify(row["quantity"]),
            }
            for row in holding_rows
        ],
        "assigned_model": assigned_model,
    }


def get_transaction_history(
    customer_id: str, ctx: Context, since: str | None = None
) -> dict[str, Any]:
    """Transaction history for one customer since an ISO-8601 timestamp, newest first (S13 §4.2)."""
    staff = resolve_staff(ctx.headers)
    _parse_customer_id(customer_id)

    since_dt: datetime | None = None
    if since is not None:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError as exc:
            raise ValueError(f"since must be an ISO-8601 timestamp: {exc}") from exc

    with UnitOfWork(customer_id=None, role=staff.role, db_role=DbRole.CHAT) as uow:
        rows = uow.session.execute(
            text(
                "SELECT journal_entry_id, entry_type, effective_date, recorded_at, memo, "
                "amount_money, quantity_units, account_role, security_id "
                "FROM v_transaction_history "
                "WHERE customer_id = :customer_id "
                "AND (CAST(:since AS timestamptz) IS NULL "
                "OR recorded_at >= CAST(:since AS timestamptz)) "
                "ORDER BY recorded_at DESC LIMIT :row_cap"
            ),
            {
                "customer_id": customer_id,
                "since": since_dt.isoformat() if since_dt is not None else None,
                "row_cap": _ROW_CAP,
            },
        ).mappings().all()

    return {
        "transactions": [
            {
                "journal_entry_id": _stringify(row["journal_entry_id"]),
                "entry_type": row["entry_type"],
                "effective_date": _stringify(row["effective_date"]),
                "recorded_at": _stringify(row["recorded_at"]),
                "memo": row["memo"],
                "amount_money": _stringify(row["amount_money"]),
                "quantity_units": _stringify(row["quantity_units"]),
                "account_role": row["account_role"],
                "security_id": _stringify(row["security_id"]),
            }
            for row in rows
        ]
    }


def list_open_reconciliation_breaks(ctx: Context) -> dict[str, Any]:
    """Aged queue of open reconciliation breaks; adviser-scope, cross-tenant (S13 §4.2, ADR 24)."""
    staff = resolve_staff(ctx.headers)

    with AgentSurfaceUnitOfWork(customer_id=None, role=staff.role) as uow:
        rows = uow.reconciliation_breaks.list_open()
        return {
            "breaks": [
                {
                    "id": str(row.id),
                    "break_type": row.break_type.value,
                    "customer_id": str(row.customer_id) if row.customer_id is not None else None,
                    "opened_at": row.opened_at.isoformat(),
                    "status": row.status.value,
                }
                for row in rows
            ]
        }


__all__ = ["get_portfolio_summary", "get_transaction_history", "list_open_reconciliation_breaks"]
