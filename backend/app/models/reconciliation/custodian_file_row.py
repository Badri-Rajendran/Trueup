"""`custodian_file_row` (S7 §5.1) — one row per source row of one morning's custodian files,
preserved verbatim before any comparison logic runs (S7 §3). Append-only; a re-delivered or
corrected file is a new `import_batch_id`, never an `UPDATE`.
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DDL, Boolean, DateTime, event, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base


def _enum_values(enum_class: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_class]


class CustodianFileType(StrEnum):
    POSITIONS = "positions"
    CASH = "cash"
    TRANSACTIONS = "transactions"


if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class CustodianFileRow(Base):
    __tablename__ = "custodian_file_row"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_type: Mapped[CustodianFileType] = mapped_column(
        SQLAlchemyEnum(CustodianFileType, name="custodian_file_type", values_callable=_enum_values),
        nullable=False,
    )
    raw_row: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    import_batch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # FR-33's "clearly labelled" requirement enforced structurally (S7 §9).
    is_simulated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Append-only enforcement (S7 §3): a preserved point-in-time fact.
event.listen(
    CustodianFileRow.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        "REVOKE UPDATE, DELETE ON custodian_file_row FROM trueup_app, trueup_worker;"
    ),
)


class CustodianFileRowRepository(BaseRepository[CustodianFileRow]):
    """No `customer_id_column`: an operational import log, not tenant-scoped data."""

    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=CustodianFileRow)


__all__ = ["CustodianFileRow", "CustodianFileRowRepository", "CustodianFileType"]
