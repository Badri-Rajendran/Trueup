"""`chat_message` (S11 §3) — the conversation transcript.

`customer_id` is denormalized from `chat_session` via a `BEFORE INSERT` trigger (S0 §7.3 RLS).
Assistant rows insert empty and finalize `content` exactly once via `chat_message_single_finalize`
(S1 §6 single-transition pattern).
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, Index, Text, event, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.chat._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ChatMessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(Base):
    __tablename__ = "chat_message"
    __table_args__ = (
        # S12 §3: S11 §6's message history query.
        Index("ix_chat_message_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False
    )
    # Denormalized from chat_session; trigger overwrites any application-set value.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[ChatMessageRole] = mapped_column(
        SQLAlchemyEnum(ChatMessageRole, name="chat_message_role", values_callable=enum_values),
        nullable=False,
    )
    # Empty string until finalized; never NULL.
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_CHAT_MESSAGE_BEFORE_INSERT_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION chat_message_denormalize_customer_id() RETURNS trigger AS $$
    BEGIN
      SELECT customer_id INTO NEW.customer_id FROM chat_session WHERE id = NEW.session_id;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_CHAT_MESSAGE_BEFORE_INSERT_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER chat_message_before_insert
      BEFORE INSERT ON chat_message
      FOR EACH ROW EXECUTE FUNCTION chat_message_denormalize_customer_id();
    """
)

# chat_message_single_finalize: content is set at most once (S1 §6 pattern).

_CHAT_MESSAGE_SINGLE_FINALIZE_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION chat_message_single_finalize() RETURNS trigger AS $$
    BEGIN
      IF OLD.content <> '' THEN
        RAISE EXCEPTION 'chat_message %% content is already finalized and cannot be updated',
          OLD.id;
      END IF;
      IF NEW.session_id <> OLD.session_id OR NEW.role <> OLD.role THEN
        RAISE EXCEPTION 'chat_message %% session_id/role cannot be changed', OLD.id;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_CHAT_MESSAGE_SINGLE_FINALIZE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER chat_message_before_update
      BEFORE UPDATE ON chat_message
      FOR EACH ROW EXECUTE FUNCTION chat_message_single_finalize();
    """
)

for _ddl in (
    _CHAT_MESSAGE_BEFORE_INSERT_FUNCTION,
    _CHAT_MESSAGE_BEFORE_INSERT_TRIGGER,
    _CHAT_MESSAGE_SINGLE_FINALIZE_FUNCTION,
    _CHAT_MESSAGE_SINGLE_FINALIZE_TRIGGER,
):
    event.listen(ChatMessage.__table__, "after_create", _ddl)

event.listen(
    ChatMessage.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS chat_message_before_update ON chat_message;"
        "DROP FUNCTION IF EXISTS chat_message_single_finalize();"
        "DROP TRIGGER IF EXISTS chat_message_before_insert ON chat_message;"
        "DROP FUNCTION IF EXISTS chat_message_denormalize_customer_id();"
    ),
)

# RLS: role-aware tenant isolation, own policy since the tenant key is denormalized (S0 §7.3).
event.listen(
    ChatMessage.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE chat_message ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_message
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    ChatMessage.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON chat_message;"
        "ALTER TABLE chat_message DISABLE ROW LEVEL SECURITY;"
    ),
)

# A transcript row is never deleted; it may be updated exactly once, per the trigger above.
event.listen(
    ChatMessage.__table__,
    "after_create",
    DDL("REVOKE DELETE ON chat_message FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class ChatMessageRepository(BaseRepository[ChatMessage]):
    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ChatMessage, customer_id_column=ChatMessage.customer_id)

    def list_for_session(self, session_id: uuid.UUID) -> list[ChatMessage]:
        return (
            self.session.query(ChatMessage)
            .filter_by(session_id=session_id)
            .order_by(ChatMessage.created_at.asc())
            .all()
        )

    def count_for_customer_since(self, customer_id: uuid.UUID, since: datetime) -> int:
        """Daily-cap check for `ChatUsageLimiter` (S11 §5.2 step 1, NFR-16); counts `user`-role messages only."""
        return (
            self.session.query(ChatMessage)
            .filter(
                ChatMessage.customer_id == customer_id,
                ChatMessage.role == ChatMessageRole.USER,
                ChatMessage.created_at >= since,
            )
            .count()
        )

    def finalize_content(self, message_id: uuid.UUID, content: str) -> None:
        """The one allowed `UPDATE`; raises if called twice for the same row."""
        message = self.session.query(ChatMessage).filter_by(id=message_id).one()
        message.content = content


__all__ = ["ChatMessage", "ChatMessageRepository", "ChatMessageRole"]
