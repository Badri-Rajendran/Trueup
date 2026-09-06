"""add S6 restatement engine

Revision ID: e7a8f234272f
Revises: 96d30b1b6cce
Create Date: 2026-09-05 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app


# revision identifiers, used by Alembic.
revision: str = 'e7a8f234272f'
down_revision: Union[str, Sequence[str], None] = '96d30b1b6cce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('published_snapshot',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('publish_watermark', sa.DateTime(timezone=True), nullable=False),
    sa.Column('twr', sa.Numeric(precision=18, scale=10), nullable=False),
    sa.Column('balance', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('holdings_json', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('published_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_published_snapshot_customer_id_customer')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_published_snapshot'))
    )
    op.create_table('restatement_event',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('affected_period_start', sa.Date(), nullable=False),
    sa.Column('affected_period_end', sa.Date(), nullable=False),
    sa.Column('trigger_type', sa.Enum('corrected_close', 'late_dividend', 'split', 'wash_sale_adjustment', 'manual_correction', name='restatement_trigger_type'), nullable=False),
    sa.Column('trigger_source_event_id', sa.UUID(), nullable=False),
    sa.Column('recomputed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_restatement_event_customer_id_customer')),
    sa.ForeignKeyConstraint(['trigger_source_event_id'], ['inbound_event.id'], name=op.f('fk_restatement_event_trigger_source_event_id_inbound_event')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_restatement_event'))
    )

    # --- RLS: role-aware tenant isolation on both S6 tables, matching sub_period_return's
    # precedent (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE published_snapshot ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON published_snapshot
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)
    op.execute("""
        ALTER TABLE restatement_event ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON restatement_event
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # --- append-only enforcement: both tables are correction-as-new-row, never UPDATE/DELETE
    # (S6 §3.1/§3.2), the same hard DB-level guarantee S1 §6 gives journal_entry/posting.
    op.execute("""
        REVOKE UPDATE, DELETE ON published_snapshot FROM trueup_app, trueup_worker;
        REVOKE UPDATE, DELETE ON restatement_event FROM trueup_app, trueup_worker;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON restatement_event;")
    op.execute("ALTER TABLE restatement_event DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON published_snapshot;")
    op.execute("ALTER TABLE published_snapshot DISABLE ROW LEVEL SECURITY;")

    op.drop_table('restatement_event')
    op.drop_table('published_snapshot')

    sa.Enum(name='restatement_trigger_type').drop(op.get_bind(), checkfirst=True)
