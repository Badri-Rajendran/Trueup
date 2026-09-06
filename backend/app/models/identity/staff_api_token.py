"""`staff_api_token` (S13 §3.2, ADR 24) — scoped, long-lived MCP bearer credential.

Only `token_hash` (SHA-256) is stored; the raw token is returned once, at issue time, and
never persisted.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


def generate_staff_api_token() -> str:
    """256 bits of CSPRNG entropy, URL-safe (ADR 24)."""
    return secrets.token_urlsafe(32)


def hash_staff_api_token(token: str) -> str:
    """SHA-256 of the raw token; the only form ever persisted."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class StaffApiToken(Base):
    __tablename__ = "staff_api_token"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No FK: predates a formal cross-schema FK convention (matches
    # reconciliation_break.resolved_by).
    staff_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StaffApiTokenRepository(BaseRepository[StaffApiToken]):
    """No `customer_id_column`: staff-scoped, not customer-scoped."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=StaffApiToken)

    def add(self, token: StaffApiToken) -> None:
        self.session.add(token)

    def get_by_id(self, token_id: uuid.UUID) -> StaffApiToken | None:
        return self.session.query(StaffApiToken).filter_by(id=token_id).first()

    def get_by_token_hash(self, token_hash: str) -> StaffApiToken | None:
        return self.session.query(StaffApiToken).filter_by(token_hash=token_hash).first()

    def list_for_staff(self, staff_id: uuid.UUID) -> list[StaffApiToken]:
        return list(
            self.session.query(StaffApiToken)
            .filter_by(staff_id=staff_id)
            .order_by(StaffApiToken.created_at.desc())
            .all()
        )

    def revoke(self, token: StaffApiToken, *, revoked_at: datetime) -> None:
        """Idempotent: revoking an already-revoked token leaves its original `revoked_at` in
        place."""
        if token.revoked_at is None:
            token.revoked_at = revoked_at


__all__ = [
    "StaffApiToken",
    "StaffApiTokenRepository",
    "generate_staff_api_token",
    "hash_staff_api_token",
]
