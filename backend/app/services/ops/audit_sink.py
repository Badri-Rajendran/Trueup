"""Concrete `AuditSink` backed by `admin_audit_log` (S0 §7.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.ops.admin_audit_log import AdminAuditLog, AdminAuditLogRepository

if TYPE_CHECKING:
    import uuid

    from app.core.uow import UnitOfWork


class SqlAuditSink:
    """Stages an `AdminAuditLog` row on the caller's `UnitOfWork`, never its own transaction."""

    def record(
        self,
        uow: UnitOfWork,
        *,
        actor_id: uuid.UUID,
        action: str,
        target_customer_id: uuid.UUID | None,
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
