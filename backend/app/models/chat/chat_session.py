"""`chat_session` (S11 §3) — one conversation.

`status` is a concurrency lock: `idle -> streaming` via conditional `UPDATE` (S11 §5.2 step 2).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, event, func, update
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.chat._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ChatSessionStatus(StrEnum):
    IDLE = "idle"
    STREAMING = "streaming"


class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customer.id"), nullable=False
    )
    status: Mapped[ChatSessionStatus] = mapped_column(
        SQLAlchemyEnum(ChatSessionStatus, name="chat_session_status", values_callable=enum_values),
        nullable=False,
        default=ChatSessionStatus.IDLE,
        server_default=ChatSessionStatus.IDLE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# Role-aware tenant-isolation RLS policy (S0 §7.3, ADR 17).
event.listen(
    ChatSession.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE chat_session ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_session
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    ChatSession.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON chat_session;"
        "ALTER TABLE chat_session DISABLE ROW LEVEL SECURITY;"
    ),
)


class ChatSessionRepository(BaseRepository[ChatSession]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ChatSession, customer_id_column=ChatSession.customer_id)

    def get_by_id(self, session_id: uuid.UUID) -> ChatSession | None:
        return self.session.query(ChatSession).filter_by(id=session_id).first()

    def list_for_customer(self, customer_id: uuid.UUID) -> list[ChatSession]:
        return (
            self.session.query(ChatSession)
            .filter_by(customer_id=customer_id)
            .order_by(ChatSession.created_at.desc())
            .all()
        )

    def try_begin_turn(self, session_id: uuid.UUID) -> bool:
        """Atomic `idle -> streaming`; `True` iff this call won the race (S11 §5.2 step 2)."""
        result = self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id, ChatSession.status == ChatSessionStatus.IDLE)
            .values(status=ChatSessionStatus.STREAMING)
        )
        # CursorResult at runtime; stubs type it as Result[Any], which has no rowcount.
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        return rowcount == 1

    def end_turn(self, session_id: uuid.UUID) -> None:
        """`streaming -> idle`, unconditionally; called in a `finally` so errors still release the lock."""
        self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(status=ChatSessionStatus.IDLE)
        )


__all__ = ["ChatSession", "ChatSessionRepository", "ChatSessionStatus"]
