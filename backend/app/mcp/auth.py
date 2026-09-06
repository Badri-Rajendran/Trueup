"""Bearer-token resolution for MCP tool calls (ADR 24, S13 §3.2/§4.1).

Revocation is re-checked on every call, never cached (S13 §6 edge case 3).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.uow import SessionRole
from app.models.identity.staff_api_token import hash_staff_api_token
from app.services.agent_surface.uow import AgentSurfaceUnitOfWork

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping


class McpAuthenticationError(RuntimeError):
    """No valid bearer credential; surfaces to the MCP client as a tool-call error."""


@dataclass(frozen=True, slots=True)
class ResolvedStaff:
    staff_id: uuid.UUID
    role: SessionRole
    label: str
    """`agent_action_request.requesting_agent` label (ADR 24)."""


def _extract_bearer(headers: Mapping[str, str] | None) -> str:
    if not headers:
        raise McpAuthenticationError("missing Authorization header")
    raw = headers.get("authorization") or headers.get("Authorization")
    if not raw or not raw.lower().startswith("bearer "):
        raise McpAuthenticationError("Authorization header must be a Bearer token")
    token = raw[len("Bearer ") :].strip()
    if not token:
        raise McpAuthenticationError("empty bearer token")
    return token


def resolve_staff(headers: Mapping[str, str] | None) -> ResolvedStaff:
    """Resolve a bearer token to its staff identity via a short-lived `UnitOfWork`."""
    token = _extract_bearer(headers)
    token_hash = hash_staff_api_token(token)
    with AgentSurfaceUnitOfWork(customer_id=None, role=SessionRole.ADMIN) as uow:
        token_row = uow.staff_api_tokens.get_by_token_hash(token_hash)
        if token_row is None or token_row.revoked_at is not None:
            raise McpAuthenticationError("invalid or revoked API token")
        staff = uow.staff.get_by_id(token_row.staff_id)
        if staff is None:
            raise McpAuthenticationError("invalid or revoked API token")
        return ResolvedStaff(
            staff_id=staff.id,
            role=SessionRole(staff.role.value),
            label=f"{staff.email} ({token_row.label})",
        )


__all__ = ["McpAuthenticationError", "ResolvedStaff", "resolve_staff"]
