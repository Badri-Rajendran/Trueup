"""`model_portfolio` (S9 §3.1) — one of exactly four (FR-7) model portfolios a customer can be
assigned to. Model portfolio *versioning* (more than one active version per model at a time) is
explicitly out of v1 scope (S9 §3.1) — this schema assumes exactly one active row per logical
model, so `is_active` is a plain flag, not a version chain.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ModelPortfolio(Base):
    __tablename__ = "model_portfolio"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class ModelPortfolioRepository(BaseRepository[ModelPortfolio]):
    """No `customer_id_column`: a model portfolio is not tenant-scoped — every customer can be
    assigned to the same one (matching `Security`'s precedent, S4 §3.3)."""

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ModelPortfolio)

    def get_by_id(self, model_portfolio_id: uuid.UUID) -> ModelPortfolio | None:
        return self.session.query(ModelPortfolio).filter_by(id=model_portfolio_id).first()

    def list_active(self) -> list[ModelPortfolio]:
        return (
            self.session.query(ModelPortfolio)
            .filter_by(is_active=True)
            .order_by(ModelPortfolio.name)
            .all()
        )


__all__ = ["ModelPortfolio", "ModelPortfolioRepository"]
