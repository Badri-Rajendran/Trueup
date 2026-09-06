"""`chat_tool_call` (S11 §3, FR-53) — audit trail of every tool invocation the agent makes.

Stores SQL text and row count, never result rows. `customer_id` denormalized from `chat_message`
via `BEFORE INSERT` trigger.
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, Integer, String, event, func
from sqlalchemy import Enum as SQLAlchemyEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.repository import BaseRepository
from app.models.base import Base
from app.models.chat._enum import enum_values

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class ChatToolName(StrEnum):
    GET_DATABASE_SCHEMA = "get_database_schema"
    EXECUTE_READ_ONLY_SQL = "execute_read_only_sql"


class ChatToolCallStatus(StrEnum):
    SUCCESS = "success"
    VALIDATOR_REJECTED = "validator_rejected"
    TIMEOUT = "timeout"
    ERROR = "error"


class ChatToolCall(Base):
    __tablename__ = "chat_tool_call"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_message.id"), nullable=False
    )
    # Denormalized from chat_message; never set by application code.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    tool_name: Mapped[ChatToolName] = mapped_column(
        SQLAlchemyEnum(ChatToolName, name="chat_tool_name", values_callable=enum_values),
        nullable=False,
    )
    # NULL for get_database_schema, which issues no query (S11 §3).
    sql_text: Mapped[str | None] = mapped_column(String, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[ChatToolCallStatus] = mapped_column(
        SQLAlchemyEnum(
            ChatToolCallStatus, name="chat_tool_call_status", values_callable=enum_values
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


_CHAT_TOOL_CALL_BEFORE_INSERT_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION chat_tool_call_denormalize_customer_id() RETURNS trigger AS $$
    BEGIN
      SELECT customer_id INTO NEW.customer_id FROM chat_message WHERE id = NEW.message_id;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_CHAT_TOOL_CALL_BEFORE_INSERT_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER chat_tool_call_before_insert
      BEFORE INSERT ON chat_tool_call
      FOR EACH ROW EXECUTE FUNCTION chat_tool_call_denormalize_customer_id();
    """
)

for _ddl in (_CHAT_TOOL_CALL_BEFORE_INSERT_FUNCTION, _CHAT_TOOL_CALL_BEFORE_INSERT_TRIGGER):
    event.listen(ChatToolCall.__table__, "after_create", _ddl)

event.listen(
    ChatToolCall.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS chat_tool_call_before_insert ON chat_tool_call;"
        "DROP FUNCTION IF EXISTS chat_tool_call_denormalize_customer_id();"
    ),
)

event.listen(
    ChatToolCall.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE chat_tool_call ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_tool_call
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    ChatToolCall.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON chat_tool_call;"
        "ALTER TABLE chat_tool_call DISABLE ROW LEVEL SECURITY;"
    ),
)

# Append-only: an audit trail row is never revised (FR-53).
event.listen(
    ChatToolCall.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON chat_tool_call FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class ChatToolCallRepository(BaseRepository[ChatToolCall]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=ChatToolCall, customer_id_column=ChatToolCall.customer_id)

    def list_for_message(self, message_id: uuid.UUID) -> list[ChatToolCall]:
        return (
            self.session.query(ChatToolCall)
            .filter_by(message_id=message_id)
            .order_by(ChatToolCall.created_at.asc())
            .all()
        )


__all__ = [
    "ChatToolCall",
    "ChatToolCallRepository",
    "ChatToolCallStatus",
    "ChatToolName",
]
