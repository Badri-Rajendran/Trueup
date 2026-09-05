"""add S4 valuation and market data

Revision ID: 263eb7564b1d
Revises: f6a4ae1f1ee7
Create Date: 2026-09-05 12:30:34.294819

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app


# revision identifiers, used by Alembic.
revision: str = '263eb7564b1d'
down_revision: Union[str, Sequence[str], None] = 'f6a4ae1f1ee7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# `market_data_source` is shared by daily_close and market_calendar_cache (S4 §3.1/§3.4) --
# created once explicitly, then referenced with create_type=False on each column so the second
# CREATE TABLE does not try to create the same Postgres enum type twice.
_market_data_source = postgresql.ENUM('live', 'simulated', name='market_data_source')


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    _market_data_source.create(bind, checkfirst=True)

    op.create_table('security',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('symbol', sa.String(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('asset_class', sa.Enum('equity', 'bond', name='security_asset_class'), nullable=False),
    sa.Column('status', sa.Enum('active', 'inactive', name='security_status'), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_security')),
    sa.UniqueConstraint('symbol', name=op.f('uq_security_symbol'))
    )
    op.create_table('market_calendar_cache',
    sa.Column('market_date', sa.Date(), nullable=False),
    sa.Column('is_trading_day', sa.Boolean(), nullable=False),
    sa.Column('session_open_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('session_close_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('source', postgresql.ENUM('live', 'simulated', name='market_data_source', create_type=False), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('market_date', name=op.f('pk_market_calendar_cache'))
    )
    op.create_table('valuation_run',
    sa.Column('market_date', sa.Date(), nullable=False),
    sa.Column('securities_expected', sa.Integer(), nullable=False),
    sa.Column('securities_confirmed', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('pending', 'complete', 'partial', name='valuation_run_status'), server_default='pending', nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('market_date', name=op.f('pk_valuation_run'))
    )
    op.create_table('daily_close',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('security_id', sa.UUID(), nullable=False),
    sa.Column('market_date', sa.Date(), nullable=False),
    sa.Column('close_price', app.core.money.PriceType(precision=18, scale=6), nullable=False),
    sa.Column('source', postgresql.ENUM('live', 'simulated', name='market_data_source', create_type=False), nullable=False),
    sa.Column('status', sa.Enum('confirmed', 'stale', 'missing', name='daily_close_status'), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['security_id'], ['security.id'], name=op.f('fk_daily_close_security_id_security')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_daily_close')),
    sa.UniqueConstraint('security_id', 'market_date', 'recorded_at', name='uq_daily_close_security_market_recorded')
    )
    op.create_table('sub_period_return',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('sub_period_start', sa.Date(), nullable=False),
    sa.Column('sub_period_end', sa.Date(), nullable=False),
    sa.Column('return_pct', sa.Numeric(precision=18, scale=10), nullable=False),
    sa.Column('value_begin', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('value_end', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('flow_amount', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('is_provisional', sa.Boolean(), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_sub_period_return_customer_id_customer')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sub_period_return')),
    sa.UniqueConstraint('customer_id', 'sub_period_start', 'sub_period_end', 'recorded_at', name='uq_sub_period_return_customer_period_recorded')
    )

    # --- RLS: role-aware tenant isolation on the one S4 table carrying a customer_id (S0 §7.3,
    # ADR 17) -- security/daily_close/market_calendar_cache/valuation_run are whole-book/whole-
    # market tables with no customer identity, matching inbound_event/job_run's precedent.
    op.execute("""
        ALTER TABLE sub_period_return ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON sub_period_return
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # --- append-only enforcement: daily_close/sub_period_return are bitemporal, correction-as-
    # new-row tables (S4 §3.1/§3.5) -- no UPDATE/DELETE grant for either runtime credential, the
    # same hard DB-level guarantee S1 §6 gives journal_entry/posting. market_calendar_cache and
    # valuation_run stay mutable (upserted in place, S4 §3.2/§3.4), so they keep the default
    # privileges docker/postgres/init.sql already grants.
    op.execute("""
        REVOKE UPDATE, DELETE ON daily_close FROM trueup_app, trueup_worker;
        REVOKE UPDATE, DELETE ON sub_period_return FROM trueup_app, trueup_worker;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sub_period_return;")
    op.execute("ALTER TABLE sub_period_return DISABLE ROW LEVEL SECURITY;")

    op.drop_table('sub_period_return')
    op.drop_table('daily_close')
    op.drop_table('valuation_run')
    op.drop_table('market_calendar_cache')
    op.drop_table('security')

    sa.Enum(name='daily_close_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='valuation_run_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='security_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='security_asset_class').drop(op.get_bind(), checkfirst=True)
    _market_data_source.drop(op.get_bind(), checkfirst=True)
