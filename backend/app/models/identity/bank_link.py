"""`bank_link` (S2 §3.3, FR-4/41/42/43) — the customer's linked external bank account.

FR-42: partial unique index enforces at most one `active` link per customer at the DB level.
`plaid_access_token` is encrypted at rest (`EncryptedText`, ADR 23).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, ForeignKey, Index, String, event, select
from sqlalchemy import DateTime as SqlDateTime
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import EncryptedText
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class BankLinkStatus(StrEnum):
    ACTIVE = "active"
    REQUIRES_REAUTH = "requires_reauth"
    SUPERSEDED = "superseded"


class BankLink(Base):
    __tablename__ = "bank_link"
    __table_args__ = (
        Index(
            "uq_bank_link_customer_active",
            "customer_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    plaid_item_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    plaid_access_token: Mapped[str] = mapped_column(EncryptedText(), nullable=False)
    status: Mapped[BankLinkStatus] = mapped_column(
        SQLAlchemyEnum(BankLinkStatus, name="bank_link_status", values_callable=_enum_values),
        nullable=False,
        default=BankLinkStatus.ACTIVE,
        server_default=BankLinkStatus.ACTIVE.value,
    )
    linked_at: Mapped[datetime] = mapped_column(
        SqlDateTime(timezone=True), nullable=False, server_default="now()"
    )


# RLS: role-aware tenant isolation (S0 §7.3, ADR 17).
event.listen(
    BankLink.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE bank_link ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON bank_link
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    BankLink.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON bank_link;"
        "ALTER TABLE bank_link DISABLE ROW LEVEL SECURITY;"
    ),
)

# DELETE revoked: a bank link is a regulatory-relevant record. UPDATE stays granted for status transitions.
event.listen(
    BankLink.__table__,
    "after_create",
    DDL("REVOKE DELETE ON bank_link FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class SqlBankLinkRepository(BaseRepository[BankLink]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=BankLink, customer_id_column=BankLink.customer_id)

    def get_by_id(self, bank_link_id: uuid.UUID) -> BankLink | None:
        statement = self._tenant_scoped(select(BankLink).where(BankLink.id == bank_link_id))
        return self.session.execute(statement).scalar_one_or_none()

    def get_by_plaid_item_id(self, plaid_item_id: str) -> BankLink | None:
        statement = self._tenant_scoped(
            select(BankLink).where(BankLink.plaid_item_id == plaid_item_id)
        )
        return self.session.execute(statement).scalar_one_or_none()

    def active_for_customer(self, customer_id: uuid.UUID) -> BankLink | None:
        statement = self._tenant_scoped(
            select(BankLink).where(
                BankLink.customer_id == customer_id,
                BankLink.status == BankLinkStatus.ACTIVE,
            )
        )
        return self.session.execute(statement).scalar_one_or_none()

    def current_for_customer(self, customer_id: uuid.UUID) -> BankLink | None:
        """The customer's not-yet-`superseded` link, `active` or `requires_reauth` (S2 §5.2/§5.4)."""
        statement = self._tenant_scoped(
            select(BankLink).where(
                BankLink.customer_id == customer_id,
                BankLink.status.in_((BankLinkStatus.ACTIVE, BankLinkStatus.REQUIRES_REAUTH)),
            )
        )
        return self.session.execute(statement).scalar_one_or_none()

    def supersede_and_activate(self, new_link: BankLink) -> None:
        """Transitions the current active/requires-reauth link to `superseded` and activates `new_link` (FR-42)."""
        existing = (
            self.session.execute(
                self._tenant_scoped(
                    select(BankLink).where(
                        BankLink.customer_id == new_link.customer_id,
                        BankLink.status.in_(
                            (BankLinkStatus.ACTIVE, BankLinkStatus.REQUIRES_REAUTH)
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )
        for link in existing:
            link.status = BankLinkStatus.SUPERSEDED
        self.add(new_link)
