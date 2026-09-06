"""`chat_message` (S11 §3) — the conversation transcript. The final natural-language answer lands
here (role `assistant`); no second copy of financial data is ever stored outside the ledger's own
tables (S11 §3's own reasoning for why `chat_tool_call` stores SQL text and a row count, not rows).

`customer_id` is not in S11 §3's literal column list -- denormalized from `chat_session.customer_id`
by a `BEFORE INSERT` trigger, the same shape `posting.customer_id` takes from `account` (S1 §3.3),
because RLS's tenant-isolation policy (S0 §7.3, ADR 17) needs a native column on *this* table to
filter on, and application code must never be trusted to set it correctly on every insert path.

**Why the assistant row is not append-only.** S11 §5.2 records each `chat_tool_call` "as it
happens, not batched at the end," but `chat_tool_call.message_id` (§3) is a required FK -- a tool
call needs a message row to attach to *before* the turn's final answer exists.
`ChatOrchestrationService` therefore inserts the assistant's `chat_message` row empty at turn
start (so tool calls have something to reference and commit against independently, preserving a
partial audit trail if the turn fails), then fills in `content` with exactly one `UPDATE` once
streaming completes.
`chat_message_single_finalize`, below, is the DB-level guarantee that this happens at most once per
row -- the same "single transition" shape `settlement_obligation_single_transition` (S1 §6) uses for
`pending -> terminal`. A `user`-role message's `content` is set once, at INSERT, and never touched
again -- the trigger does not need to distinguish the two roles to enforce that.
"""

from __future__ import annotations

import uuid
from datetime import (
    datetime,  # noqa: TC003 -- SQLAlchemy resolves mapped annotations at import time.
)
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import DDL, DateTime, ForeignKey, Text, event, func
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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_session.id"), nullable=False
    )
    # Denormalized from chat_session -- see module docstring. Never set by application code; the
    # trigger below always overwrites whatever the ORM sends for this column.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    role: Mapped[ChatMessageRole] = mapped_column(
        SQLAlchemyEnum(ChatMessageRole, name="chat_message_role", values_callable=enum_values),
        nullable=False,
    )
    # Empty string at INSERT for a not-yet-finalized assistant row -- see module docstring. Never
    # NULL, so `chat_message_single_finalize`'s `OLD.content <> ''` check has one shape to test.
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

# --- chat_message_single_finalize: content is set at most once past its initial '' (module
# docstring) -- mirrors settlement_obligation_single_transition's shape (S1 §6). ------------------

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
        """`ChatUsageLimiter`'s daily-cap check (S11 §5.2 step 1, NFR-16) -- counts `user`-role
        messages only, since an `assistant` reply is never itself a billable query."""
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
        """The one allowed `UPDATE` -- see module docstring. Raises the DB's own exception (via
        `chat_message_single_finalize`) if called twice for the same row."""
        message = self.session.query(ChatMessage).filter_by(id=message_id).one()
        message.content = content


__all__ = ["ChatMessage", "ChatMessageRepository", "ChatMessageRole"]
