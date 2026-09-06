"""S13's three write tools (S13 §4.2, ADR 24). Each validates arguments, then inserts one
`pending` `agent_action_request` row -- never touches `order`/`kyc_status`/`reconciliation_break`
directly; that happens only on human approval (`app/controllers/admin/agent_requests.py`).
"""

from __future__ import annotations

import uuid
from typing import Any

from mcp.server.mcpserver import (
    Context,  # noqa: TC002 -- needed at runtime for schema introspection.
)

from app.mcp.auth import resolve_staff
from app.models.ops.agent_action_request import AgentActionType
from app.services.agent_surface.uow import AgentSurfaceUnitOfWork


def _parse_uuid(raw: str, *, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UUID: {exc}") from exc


def _require_text(raw: str, *, field: str) -> str:
    stripped = raw.strip()
    if not stripped:
        raise ValueError(f"{field} is required")
    return raw


def propose_reconciliation_break_resolution(
    break_id: str, resolution_note: str, ctx: Context
) -> dict[str, Any]:
    """Propose a resolution for a reconciliation break (S13 §4.2)."""
    staff = resolve_staff(ctx.headers)
    break_uuid = _parse_uuid(break_id, field="break_id")
    resolution_note = _require_text(resolution_note, field="resolution_note")

    with AgentSurfaceUnitOfWork(customer_id=None, role=staff.role) as uow:
        if uow.reconciliation_breaks.get_by_id(break_uuid) is None:
            raise ValueError(f"reconciliation_break {break_id} not found")

        request_id = uow.agent_action_requests.create(
            action=AgentActionType.RESOLVE_BREAK,
            arguments={"break_id": break_id, "resolution_note": resolution_note},
            requesting_agent=staff.label,
            justification=resolution_note,
        )
        uow.commit()

    return {"request_id": str(request_id), "status": "pending"}


def propose_kyc_override(customer_id: str, reason: str, ctx: Context) -> dict[str, Any]:
    """Propose reopening a locked customer's KYC status (S13 §4.2)."""
    staff = resolve_staff(ctx.headers)
    customer_uuid = _parse_uuid(customer_id, field="customer_id")
    reason = _require_text(reason, field="reason")

    with AgentSurfaceUnitOfWork(customer_id=None, role=staff.role) as uow:
        if uow.customers.get_by_id(customer_uuid) is None:
            raise ValueError(f"customer {customer_id} not found")

        request_id = uow.agent_action_requests.create(
            action=AgentActionType.KYC_OVERRIDE,
            arguments={"customer_id": customer_id, "reason": reason},
            requesting_agent=staff.label,
            justification=reason,
        )
        uow.commit()

    return {"request_id": str(request_id), "status": "pending"}


def propose_rebalance(customer_id: str, ctx: Context) -> dict[str, Any]:
    """Propose an ad-hoc rebalance evaluation for one customer (S13 §4.2)."""
    staff = resolve_staff(ctx.headers)
    customer_uuid = _parse_uuid(customer_id, field="customer_id")

    with AgentSurfaceUnitOfWork(customer_id=None, role=staff.role) as uow:
        if uow.customers.get_by_id(customer_uuid) is None:
            raise ValueError(f"customer {customer_id} not found")

        request_id = uow.agent_action_requests.create(
            action=AgentActionType.REBALANCE,
            arguments={"customer_id": customer_id},
            requesting_agent=staff.label,
            justification=(
                f"ad-hoc rebalance evaluation requested via the MCP agent surface for "
                f"customer {customer_id}"
            ),
        )
        uow.commit()

    return {"request_id": str(request_id), "status": "pending"}


__all__ = ["propose_kyc_override", "propose_rebalance", "propose_reconciliation_break_resolution"]
