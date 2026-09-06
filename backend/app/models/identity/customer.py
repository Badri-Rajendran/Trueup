from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum

from flask_login import UserMixin
from sqlalchemy import DDL, DateTime, event, text
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class KycStatus(StrEnum):
    """StrEnum so members compare equal to their string literal (matches every DB-backed status column)."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class AccountApprovalStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class Customer(Base, UserMixin):  # type: ignore[misc, no-any-unimported]  # flask_login ships no py.typed marker
    __tablename__ = "customer"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(unique=True, index=True)
    password_hash: Mapped[str]
    kyc_status: Mapped[KycStatus] = mapped_column(
        SQLAlchemyEnum(KycStatus), default=KycStatus.pending
    )
    account_approval_status: Mapped[AccountApprovalStatus] = mapped_column(
        SQLAlchemyEnum(AccountApprovalStatus), default=AccountApprovalStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=text("now()"),
    )

    @property
    def role(self) -> str:
        return "customer"

    def get_id(self) -> str:
        return str(self.id)


# S0 §7.3's tenant-isolation RLS policy (ADR 17), attached to the table's DDL lifecycle.
event.listen(
    Customer.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE customer ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON customer
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    Customer.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON customer;"
        "ALTER TABLE customer DISABLE ROW LEVEL SECURITY;"
    ),
)
