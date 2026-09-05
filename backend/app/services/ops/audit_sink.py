"""The concrete `AuditSink` (`app/core/security.py`) backed by `admin_audit_log` (S0 §7.2).

Lives in `app/services/` rather than `app/core/` because it imports the concrete
`AdminAuditLog` model — exactly the dependency `core/security.py`'s `AuditSink` Protocol exists
to invert. Installed once at startup via `app.core.security.set_audit_sink()`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.ops.admin_audit_log import AdminAuditLog, AdminAuditLogRepository

if TYPE_CHECKING:
    import uuid

    from app.core.uow import UnitOfWork


class SqlAuditSink:
    """Stages an `AdminAuditLog` row via the append-only repository bound to the caller's
    `UnitOfWork` — never its own transaction, so the audit write and the action it records
    commit or roll back together."""

    def record(
        self,
        uow: UnitOfWork,
        *,
        actor_id: uuid.UUID,
        action: str,
        target_customer_id: uuid.UUID,
        payload_hash: str,
    ) -> None:
        AdminAuditLogRepository(uow).add(
            AdminAuditLog(
                actor_id=actor_id,
                action=action,
                target_customer_id=target_customer_id,
                payload_hash=payload_hash,
            )
        )
