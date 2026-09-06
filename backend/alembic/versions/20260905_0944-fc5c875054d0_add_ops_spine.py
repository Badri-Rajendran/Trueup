"""add ops spine

Revision ID: fc5c875054d0
Revises: 
Create Date: 2026-09-05 09:44:22.606379

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'fc5c875054d0'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('admin_audit_log',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=False),
    sa.Column('action', sa.String(length=255), nullable=False),
    sa.Column('target_customer_id', sa.UUID(), nullable=False),
    sa.Column('payload_hash', sa.String(length=64), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_admin_audit_log'))
    )
    op.create_index('ix_admin_audit_log_customer_recorded', 'admin_audit_log', ['target_customer_id', 'recorded_at'], unique=False)
    op.create_table('idempotency_key',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('key', sa.String(length=255), nullable=False),
    sa.Column('request_hash', sa.String(length=64), nullable=False),
    sa.Column('response_status', sa.Integer(), nullable=False),
    sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_idempotency_key')),
    sa.UniqueConstraint('customer_id', 'key', name='uq_idempotency_key_customer_key')
    )
    op.create_table('inbound_event',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('source', sa.Enum('alpaca', 'plaid', 'stripe', 'marketdata', 'custodian_file', name='inbound_event_source'), nullable=False),
    sa.Column('source_event_id', sa.String(length=255), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('signature_verified', sa.Boolean(), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.Enum('received', 'processing', 'processed', 'failed', 'unmatched', name='inbound_event_status'), server_default='received', nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('last_error', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_inbound_event')),
    sa.UniqueConstraint('source', 'source_event_id', name='uq_inbound_event_source_event')
    )
    op.create_table('job_outbox',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('task', sa.String(length=255), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
    sa.Column('next_attempt_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('status', sa.Enum('pending', 'processing', 'completed', 'dead_letter', name='job_outbox_status'), server_default='pending', nullable=False),
    sa.Column('locked_by', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_outbox'))
    )
    op.create_table('job_run',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('job_name', sa.String(length=255), nullable=False),
    sa.Column('cadence', sa.Enum('daily', 'monthly', 'continuous', name='job_cadence'), nullable=False),
    sa.Column('market_date', sa.Date(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('status', sa.Enum('started', 'completed', 'failed', 'skipped', name='job_run_status'), server_default='started', nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_job_run'))
    )
    op.create_index('uq_job_run_daily_name_market_date', 'job_run', ['job_name', 'market_date'], unique=True, postgresql_where=sa.text("cadence = 'daily'"))
    # date_trunc() is STABLE not IMMUTABLE in Postgres; wrap it so it can be used in an index expression.
    op.execute("""
        CREATE OR REPLACE FUNCTION job_run_month_start(d date) RETURNS date AS $$
            SELECT date_trunc('month', d)::date
        $$ LANGUAGE sql IMMUTABLE;
    """)
    op.create_index(
        'uq_job_run_monthly_name_market_month',
        'job_run',
        ['job_name', sa.text('job_run_month_start(market_date)')],
        unique=True,
        postgresql_where=sa.text("cadence = 'monthly'"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('uq_job_run_monthly_name_market_month', table_name='job_run', postgresql_where=sa.text("cadence = 'monthly'"))
    op.execute("DROP FUNCTION IF EXISTS job_run_month_start(date);")
    op.drop_index('uq_job_run_daily_name_market_date', table_name='job_run', postgresql_where=sa.text("cadence = 'daily'"))
    op.drop_table('job_run')
    op.drop_table('job_outbox')
    op.drop_table('inbound_event')
    op.drop_table('idempotency_key')
    op.drop_index('ix_admin_audit_log_customer_recorded', table_name='admin_audit_log')
    op.drop_table('admin_audit_log')
    # drop_table() does not drop the Postgres ENUM types created alongside these tables.
    sa.Enum(name='job_run_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='job_cadence').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='job_outbox_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='inbound_event_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='inbound_event_source').drop(op.get_bind(), checkfirst=True)
