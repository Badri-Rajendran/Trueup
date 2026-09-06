"""add S11 chat assistant tables and curated views

Revision ID: 9b1c7a4f3d02
Revises: 42545d3cedde
Create Date: 2026-09-05 17:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.models.chat.curated_views import (
    CREATE_CURATED_VIEWS_SQL,
    DROP_CURATED_VIEWS_SQL,
    GRANT_CURATED_VIEWS_SQL,
)

# revision identifiers, used by Alembic.
revision: str = '9b1c7a4f3d02'
down_revision: str | Sequence[str] | None = '42545d3cedde'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'chat_session',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('idle', 'streaming', name='chat_session_status'),
            server_default='idle',
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_chat_session_customer_id_customer')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_session')),
    )
    op.create_table(
        'chat_message',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('session_id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('role', sa.Enum('user', 'assistant', name='chat_message_role'), nullable=False),
        sa.Column('content', sa.Text(), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['chat_session.id'], name=op.f('fk_chat_message_session_id_chat_session')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_message')),
    )
    op.create_table(
        'chat_tool_call',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('message_id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=True),
        sa.Column('tool_name', sa.Enum('get_database_schema', 'execute_read_only_sql', name='chat_tool_name'), nullable=False),
        sa.Column('sql_text', sa.String(), nullable=True),
        sa.Column('row_count', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('success', 'validator_rejected', 'timeout', 'error', name='chat_tool_call_status'),
            nullable=False,
        ),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['message_id'], ['chat_message.id'], name=op.f('fk_chat_tool_call_message_id_chat_message')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_chat_tool_call')),
    )

    # RLS tenant isolation (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE chat_session ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_session
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );

        ALTER TABLE chat_message ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_message
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );

        ALTER TABLE chat_tool_call ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON chat_tool_call
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # customer_id denormalization triggers (chat_message from chat_session, chat_tool_call from chat_message).
    op.execute("""
        CREATE OR REPLACE FUNCTION chat_message_denormalize_customer_id() RETURNS trigger AS $$
        BEGIN
          SELECT customer_id INTO NEW.customer_id FROM chat_session WHERE id = NEW.session_id;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER chat_message_before_insert
          BEFORE INSERT ON chat_message
          FOR EACH ROW EXECUTE FUNCTION chat_message_denormalize_customer_id();

        CREATE OR REPLACE FUNCTION chat_tool_call_denormalize_customer_id() RETURNS trigger AS $$
        BEGIN
          SELECT customer_id INTO NEW.customer_id FROM chat_message WHERE id = NEW.message_id;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER chat_tool_call_before_insert
          BEFORE INSERT ON chat_tool_call
          FOR EACH ROW EXECUTE FUNCTION chat_tool_call_denormalize_customer_id();
    """)

    # chat_message_single_finalize: content moves past '' at most once (mirrors S1 §6).
    op.execute("""
        CREATE OR REPLACE FUNCTION chat_message_single_finalize() RETURNS trigger AS $$
        BEGIN
          IF OLD.content <> '' THEN
            RAISE EXCEPTION 'chat_message % content is already finalized and cannot be updated',
              OLD.id;
          END IF;
          IF NEW.session_id <> OLD.session_id OR NEW.role <> OLD.role THEN
            RAISE EXCEPTION 'chat_message % session_id/role cannot be changed', OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER chat_message_before_update
          BEFORE UPDATE ON chat_message
          FOR EACH ROW EXECUTE FUNCTION chat_message_single_finalize();
    """)

    # Append-only enforcement (FR-53).
    op.execute("""
        REVOKE DELETE ON chat_message FROM trueup_app, trueup_worker;
        REVOKE UPDATE, DELETE ON chat_tool_call FROM trueup_app, trueup_worker;
    """)

    # Curated read-model views + GRANT to chat_readonly (ADR 19).
    op.execute(CREATE_CURATED_VIEWS_SQL)
    op.execute(GRANT_CURATED_VIEWS_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute(DROP_CURATED_VIEWS_SQL)

    op.execute("DROP TRIGGER IF EXISTS chat_message_before_update ON chat_message;")
    op.execute("DROP FUNCTION IF EXISTS chat_message_single_finalize();")
    op.execute("DROP TRIGGER IF EXISTS chat_tool_call_before_insert ON chat_tool_call;")
    op.execute("DROP FUNCTION IF EXISTS chat_tool_call_denormalize_customer_id();")
    op.execute("DROP TRIGGER IF EXISTS chat_message_before_insert ON chat_message;")
    op.execute("DROP FUNCTION IF EXISTS chat_message_denormalize_customer_id();")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON chat_tool_call;")
    op.execute("ALTER TABLE chat_tool_call DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON chat_message;")
    op.execute("ALTER TABLE chat_message DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON chat_session;")
    op.execute("ALTER TABLE chat_session DISABLE ROW LEVEL SECURITY;")

    op.drop_table('chat_tool_call')
    op.drop_table('chat_message')
    op.drop_table('chat_session')
    sa.Enum(name='chat_tool_call_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='chat_tool_name').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='chat_message_role').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='chat_session_status').drop(op.get_bind(), checkfirst=True)
