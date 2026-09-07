"""`security` (S4 §3.3) — the instrument master.

Deliberately minimal; no customer-facing endpoint creates one, so `symbol` is never user input.
No FK from `account.security_id`/`order.security_id`; both predate this spec (S4 §3.3).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, func, select
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.ledger._enum import enum_values

if TYPE_CHECKING:
    from collections.abc import Sequence

    from app.core.uow import UnitOfWork


class SecurityAssetClass(StrEnum):
    EQUITY = "equity"
    BOND = "bond"


class SecurityStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Security(Base):
    __tablename__ = "security"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    asset_class: Mapped[SecurityAssetClass] = mapped_column(
        SQLAlchemyEnum(
            SecurityAssetClass, name="security_asset_class", values_callable=enum_values
        ),
        nullable=False,
    )
    status: Mapped[SecurityStatus] = mapped_column(
        SQLAlchemyEnum(SecurityStatus, name="security_status", values_callable=enum_values),
        nullable=False,
        default=SecurityStatus.ACTIVE,
        server_default=SecurityStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SecurityRepository(BaseRepository[Security]):
    """No `customer_id_column`: a security is not tenant-scoped."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Security)

    def get_by_id(self, security_id: uuid.UUID) -> Security | None:
        return self.session.query(Security).filter_by(id=security_id).first()

    def get_by_symbol(self, symbol: str) -> Security | None:
        return self.session.query(Security).filter_by(symbol=symbol).first()

    def list_by_ids(self, security_ids: Sequence[uuid.UUID]) -> list[Security]:
        """Batched fetch for a list read that touches many securities at once (GET /api/v1/lots)."""
        if not security_ids:
            return []
        statement = select(Security).where(Security.id.in_(security_ids))
        return list(self.session.execute(statement).scalars().all())
