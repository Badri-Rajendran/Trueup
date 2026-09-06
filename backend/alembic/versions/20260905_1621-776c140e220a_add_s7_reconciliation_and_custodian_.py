"""add s7 reconciliation and custodian simulator

Revision ID: 776c140e220a
Revises: e7a8f234272f
Create Date: 2026-09-05 16:21:42.198113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '776c140e220a'
down_revision: Union[str, Sequence[str], None] = 'e7a8f234272f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('custodian_file_row',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('file_type', sa.Enum('positions', 'cash', 'transactions', name='custodian_file_type'), nullable=False),
    sa.Column('raw_row', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('import_batch_id', sa.UUID(), nullable=False),
    sa.Column('is_simulated', sa.Boolean(), nullable=False),
    sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_custodian_file_row'))
    )
    op.create_table('reconciliation_break',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('break_type', sa.Enum('position_mismatch', 'cash_mismatch', 'unmatched_custodian_transaction', 'unmatched_internal_transaction', name='reconciliation_break_type'), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=True),
    sa.Column('expected', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('actual', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('opened_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('status', sa.Enum('open', 'resolved', name='reconciliation_break_status'), server_default='open', nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('resolved_by', sa.UUID(), nullable=True),
    sa.Column('resolution_note', sa.String(), nullable=True),
    sa.Column('import_batch_id', sa.UUID(), nullable=False),
    sa.CheckConstraint("(status <> 'resolved') OR (resolved_by IS NOT NULL)", name=op.f('ck_reconciliation_break_resolved_break_requires_resolver')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reconciliation_break'))
    )

    # Append-only enforcement (S7 §3/§5.2).
    op.execute("REVOKE UPDATE, DELETE ON custodian_file_row FROM trueup_app, trueup_worker;")
    op.execute("REVOKE DELETE ON reconciliation_break FROM trueup_app, trueup_worker;")

    # Single-transition + immutable-identifying-fields trigger (S7 §5.2, FR-44).
    op.execute("""
        CREATE OR REPLACE FUNCTION reconciliation_break_single_transition() RETURNS trigger AS $$
        BEGIN
          IF OLD.status <> 'open' THEN
            RAISE EXCEPTION 'reconciliation_break % is already terminal (%) and cannot be updated',
              OLD.id, OLD.status;
          END IF;
          IF NEW.break_type <> OLD.break_type
             OR NEW.customer_id IS DISTINCT FROM OLD.customer_id
             OR NEW.expected IS DISTINCT FROM OLD.expected
             OR NEW.actual IS DISTINCT FROM OLD.actual
             OR NEW.opened_at <> OLD.opened_at
             OR NEW.import_batch_id <> OLD.import_batch_id THEN
            RAISE EXCEPTION
              'reconciliation_break % identifying fields are immutable once created (S7 section 5.2)',
              OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER reconciliation_break_before_update
          BEFORE UPDATE ON reconciliation_break
          FOR EACH ROW EXECUTE FUNCTION reconciliation_break_single_transition();
    """)

    # RLS tenant isolation (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE reconciliation_break ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON reconciliation_break
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON reconciliation_break;")
    op.execute("ALTER TABLE reconciliation_break DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP TRIGGER IF EXISTS reconciliation_break_before_update ON reconciliation_break;")
    op.execute("DROP FUNCTION IF EXISTS reconciliation_break_single_transition();")

    op.drop_table('reconciliation_break')
    op.drop_table('custodian_file_row')

    sa.Enum(name='reconciliation_break_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='reconciliation_break_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='custodian_file_type').drop(op.get_bind(), checkfirst=True)
