"""add bank_link and kyc_session tables

Revision ID: c4a1e9f7b3d5
Revises: 2fe8f869c21b
Create Date: 2026-09-06 03:00:00.000000

bank_link and kyc_session (S2 §3.2/§3.3) were missing their migration; catches the schema up.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app


# revision identifiers, used by Alembic.
revision: str = 'c4a1e9f7b3d5'
down_revision: Union[str, Sequence[str], None] = '2fe8f869c21b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'bank_link',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=False),
        sa.Column('plaid_item_id', sa.String(), nullable=False),
        sa.Column('plaid_access_token', app.core.crypto.EncryptedText(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('active', 'requires_reauth', 'superseded', name='bank_link_status'),
            nullable=False,
            server_default='active',
        ),
        sa.Column(
            'linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_bank_link_customer_id_customer')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_bank_link')),
        sa.UniqueConstraint('plaid_item_id', name=op.f('uq_bank_link_plaid_item_id')),
    )
    op.create_index(
        'uq_bank_link_customer_active',
        'bank_link',
        ['customer_id'],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        'kyc_session',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('customer_id', sa.Uuid(), nullable=False),
        sa.Column('provider_session_id', sa.String(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('pending', 'approved', 'rejected', name='kyc_session_status'),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False
        ),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_kyc_session_customer_id_customer')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_kyc_session')),
        sa.UniqueConstraint('provider_session_id', name=op.f('uq_kyc_session_provider_session_id')),
    )

    # kyc_session: status transitions exactly once, pending -> terminal (S2 §3.2).
    op.execute("""
        CREATE OR REPLACE FUNCTION kyc_session_single_transition() RETURNS trigger AS $$
        BEGIN
          IF OLD.status <> 'pending' THEN
            RAISE EXCEPTION 'kyc_session % is already terminal (%) and cannot be updated',
              OLD.id, OLD.status;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER kyc_session_before_update
          BEFORE UPDATE ON kyc_session
          FOR EACH ROW EXECUTE FUNCTION kyc_session_single_transition();
    """)

    # RLS tenant isolation (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE bank_link ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON bank_link
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );

        ALTER TABLE kyc_session ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON kyc_session
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # Regulatory records -- DELETE revoked for both runtime roles.
    op.execute("""
        REVOKE DELETE ON bank_link FROM trueup_app, trueup_worker;
        REVOKE DELETE ON kyc_session FROM trueup_app, trueup_worker;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON kyc_session;")
    op.execute("ALTER TABLE kyc_session DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON bank_link;")
    op.execute("ALTER TABLE bank_link DISABLE ROW LEVEL SECURITY;")

    op.execute("DROP TRIGGER IF EXISTS kyc_session_before_update ON kyc_session;")
    op.execute("DROP FUNCTION IF EXISTS kyc_session_single_transition();")

    op.drop_table('kyc_session')
    op.drop_index('uq_bank_link_customer_active', table_name='bank_link')
    op.drop_table('bank_link')

    sa.Enum(name='kyc_session_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='bank_link_status').drop(op.get_bind(), checkfirst=True)
