"""`chat_session` (S11 §3) — one conversation. `status` is the concurrency lock
`ChatOrchestrationService` acquires before running a turn (S11 §5.2 step 2): `idle -> streaming` is
a single conditional `UPDATE ... WHERE status = 'idle'`, so two concurrent turns on the same session
can never both proceed -- the loser's `UPDATE` affects zero rows, not a race decided by whichever
service instance reads `status` last.
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


# S0 §7.3's role-aware tenant-isolation RLS policy (ADR 17) -- native customer_id, same shape as
# `account`/`tax_lot`.
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
        """Atomic `idle -> streaming`. `True` iff this call won the race (S11 §5.2 step 2) --
        a second concurrent call for the same session sees `rowcount == 0` and must reject the
        turn as "still answering," never run a second agent loop against the same conversation."""
        result = self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id, ChatSession.status == ChatSessionStatus.IDLE)
            .values(status=ChatSessionStatus.STREAMING)
        )
        # `Session.execute()` of an `Update` is a `CursorResult` at runtime; SQLAlchemy's stubs
        # type it as the more general `Result[Any]`, which has no `rowcount`.
        rowcount: int = result.rowcount  # type: ignore[attr-defined]
        return rowcount == 1

    def end_turn(self, session_id: uuid.UUID) -> None:
        """`streaming -> idle`, unconditionally -- called once per turn, in a `finally`, so a turn
        that errors mid-stream still releases the lock rather than stranding the session."""
        self.session.execute(
            update(ChatSession)
            .where(ChatSession.id == session_id)
            .values(status=ChatSessionStatus.IDLE)
        )


__all__ = ["ChatSession", "ChatSessionRepository", "ChatSessionStatus"]
