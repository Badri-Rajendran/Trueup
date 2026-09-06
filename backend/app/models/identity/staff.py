from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum

from flask_login import UserMixin
from sqlalchemy import DateTime, text
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.models.base import Base


class StaffRole(StrEnum):
    """StrEnum so `Staff.role` compares as a bare string, matching `AuthPrincipal` (S0 §7.2)."""

    adviser = "adviser"
    admin = "admin"


class Staff(Base, UserMixin):  # type: ignore[misc, no-any-unimported]  # flask_login ships no py.typed marker
    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    role: Mapped[StaffRole] = mapped_column(SQLAlchemyEnum(StaffRole))
    totp_secret_encrypted: Mapped[str | None] = mapped_column(EncryptedText(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    def get_id(self) -> str:
        return str(self.id)
