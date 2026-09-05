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
    """Plain enum.Enum members compare False against a string literal without an explicit
    `.value` — the exact bug found and fixed on `StaffRole` this wave. StrEnum everywhere,
    matching every other DB-backed status column in this codebase, closes it before S2 gives
    these columns their first real reader."""

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


# S0 §7.3's tenant-isolation RLS policy, attached directly to the table's own DDL lifecycle rather
# than living only in the Alembic migration — so any path that creates `customer` via SQLAlchemy
# metadata (a test fixture, e.g.) gets the real policy too, with no risk of drifting from what the
# migration actually ships. `NULLIF(...)` avoids depending on Postgres evaluating this OR
# left-to-right: an adviser/admin session leaves `app.customer_id` unset (''), and NULL::uuid is
# NULL rather than an error, so `id = NULL` is simply excluded, not raised, regardless of
# evaluation order (see the migration's own comment, and ADR 17). SQLAlchemy's DDL.__init__ ships
# with no type annotations, hence the ignores below.
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
