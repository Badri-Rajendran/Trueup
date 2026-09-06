"""add S10 performance fees

Revision ID: 2fe8f869c21b
Revises: 80985c1b5653
Create Date: 2026-09-05 20:10:00.000000

Add S10 performance fee account roles and six tables (S10 §3, ADR 10).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

import app


# revision identifiers, used by Alembic.
revision: str = '2fe8f869c21b'
down_revision: Union[str, Sequence[str], None] = '80985c1b5653'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CONSTRAINT_SQL = (
    "(role = 'cash' AND dimension = 'money') OR "
    "(role = 'customer_equity' AND dimension = 'money') OR "
    "(role = 'position_units' AND dimension = 'units') OR "
    "(role = 'position_cost' AND dimension = 'money') OR "
    "(role = 'fees_expense' AND dimension = 'money') OR "
    "(role = 'dividend_income' AND dimension = 'money') OR "
    "(role = 'customer_receivable' AND dimension = 'money') OR "
    "(role = 'dividend_receivable' AND dimension = 'money') OR "
    "(role = 'realized_gain_loss' AND dimension = 'money')"
)
_NEW_CONSTRAINT_SQL = (
    _OLD_CONSTRAINT_SQL
    + " OR (role = 'fees_accrued_payable' AND dimension = 'money')"
    + " OR (role = 'fee_revenue_accrued' AND dimension = 'money')"
    + " OR (role = 'fee_revenue_collected' AND dimension = 'money')"
)


def upgrade() -> None:
    """Upgrade schema."""
    # S10's three new account roles (ADR 10).
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'fees_accrued_payable';")
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'fee_revenue_accrued';")
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'fee_revenue_collected';")

    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")
    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _NEW_CONSTRAINT_SQL)

    # high_water_mark (S10 §3.2) -- one row per customer, updated in place.
    op.create_table(
        'high_water_mark',
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('peak_value', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_high_water_mark_customer_id_customer')),
        sa.PrimaryKeyConstraint('customer_id', name=op.f('pk_high_water_mark')),
    )
    op.execute("""
        ALTER TABLE high_water_mark ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON high_water_mark
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # fee_accrual (S10 §3.3) -- append-only, UNIQUE(customer_id, accrual_date).
    op.create_table(
        'fee_accrual',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('accrual_date', sa.Date(), nullable=False),
        sa.Column('gain_amount', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
        sa.Column('fee_amount', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
        sa.Column('journal_entry_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_fee_accrual_customer_id_customer')),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], name=op.f('fk_fee_accrual_journal_entry_id_journal_entry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fee_accrual')),
        sa.UniqueConstraint('customer_id', 'accrual_date', name='uq_fee_accrual_customer_date'),
    )
    op.execute("""
        ALTER TABLE fee_accrual ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_accrual
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)
    op.execute("REVOKE UPDATE, DELETE ON fee_accrual FROM trueup_app, trueup_worker;")

    # fee_charge (S10 §3.4).
    op.create_table(
        'fee_charge',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('billing_period_start', sa.Date(), nullable=False),
        sa.Column('billing_period_end', sa.Date(), nullable=False),
        sa.Column('total_accrued', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
        sa.Column('as_published_watermark', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Enum('pending', 'succeeded', 'failed', 'dunning', name='fee_charge_status'), nullable=False, server_default='pending'),
        sa.Column('stripe_charge_id', sa.String(length=255), nullable=True),
        sa.Column('journal_entry_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_fee_charge_customer_id_customer')),
        sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], name=op.f('fk_fee_charge_journal_entry_id_journal_entry')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fee_charge')),
        sa.UniqueConstraint('stripe_charge_id', name=op.f('uq_fee_charge_stripe_charge_id')),
    )
    op.execute("""
        ALTER TABLE fee_charge ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_charge
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)
    # `as_published_watermark` is immutable once set, DB-enforced (FR-47).
    op.execute("""
        CREATE OR REPLACE FUNCTION fee_charge_watermark_immutable() RETURNS trigger AS $$
        BEGIN
          IF OLD.as_published_watermark IS NOT NULL
             AND NEW.as_published_watermark IS DISTINCT FROM OLD.as_published_watermark THEN
            RAISE EXCEPTION
              'fee_charge.as_published_watermark is immutable once set (FR-47), row %',
              OLD.id;
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER fee_charge_watermark_immutable
          BEFORE UPDATE ON fee_charge
          FOR EACH ROW EXECUTE FUNCTION fee_charge_watermark_immutable();
    """)

    # dunning_state (S10 §3.5).
    op.create_table(
        'dunning_state',
        sa.Column('fee_charge_id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('attempt_number', sa.Integer(), nullable=False),
        sa.Column('next_retry_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('status', sa.Enum('retrying', 'exhausted', name='dunning_status'), nullable=False, server_default='retrying'),
        sa.ForeignKeyConstraint(['fee_charge_id'], ['fee_charge.id'], name=op.f('fk_dunning_state_fee_charge_id_fee_charge')),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_dunning_state_customer_id_customer')),
        sa.PrimaryKeyConstraint('fee_charge_id', name=op.f('pk_dunning_state')),
    )
    op.execute("""
        ALTER TABLE dunning_state ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON dunning_state
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # fee_restatement_disclosure (S10 §6) -- append-only.
    op.create_table(
        'fee_restatement_disclosure',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('fee_charge_id', sa.UUID(), nullable=False),
        sa.Column('restatement_event_id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_fee_restatement_disclosure_customer_id_customer')),
        sa.ForeignKeyConstraint(['fee_charge_id'], ['fee_charge.id'], name=op.f('fk_fee_restatement_disclosure_fee_charge_id_fee_charge')),
        sa.ForeignKeyConstraint(['restatement_event_id'], ['restatement_event.id'], name=op.f('fk_fee_restatement_disclosure_restatement_event_id_restatement_event')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_fee_restatement_disclosure')),
    )
    op.execute("""
        ALTER TABLE fee_restatement_disclosure ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON fee_restatement_disclosure
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)
    op.execute(
        "REVOKE UPDATE, DELETE ON fee_restatement_disclosure FROM trueup_app, trueup_worker;"
    )

    # payment_method (S10 §7).
    op.create_table(
        'payment_method',
        sa.Column('customer_id', sa.UUID(), nullable=False),
        sa.Column('stripe_customer_id', sa.String(length=255), nullable=False),
        sa.Column('stripe_payment_method_id', sa.String(length=255), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_payment_method_customer_id_customer')),
        sa.PrimaryKeyConstraint('customer_id', name=op.f('pk_payment_method')),
    )
    op.execute("""
        ALTER TABLE payment_method ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON payment_method
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON payment_method;")
    op.execute("ALTER TABLE payment_method DISABLE ROW LEVEL SECURITY;")
    op.drop_table('payment_method')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fee_restatement_disclosure;")
    op.execute("ALTER TABLE fee_restatement_disclosure DISABLE ROW LEVEL SECURITY;")
    op.drop_table('fee_restatement_disclosure')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON dunning_state;")
    op.execute("ALTER TABLE dunning_state DISABLE ROW LEVEL SECURITY;")
    op.drop_table('dunning_state')

    op.execute("DROP TRIGGER IF EXISTS fee_charge_watermark_immutable ON fee_charge;")
    op.execute("DROP FUNCTION IF EXISTS fee_charge_watermark_immutable();")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fee_charge;")
    op.execute("ALTER TABLE fee_charge DISABLE ROW LEVEL SECURITY;")
    op.drop_table('fee_charge')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON fee_accrual;")
    op.execute("ALTER TABLE fee_accrual DISABLE ROW LEVEL SECURITY;")
    op.drop_table('fee_accrual')

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON high_water_mark;")
    op.execute("ALTER TABLE high_water_mark DISABLE ROW LEVEL SECURITY;")
    op.drop_table('high_water_mark')

    sa.Enum(name='dunning_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='fee_charge_status').drop(op.get_bind(), checkfirst=True)

    # Drop the CHECK constraint before rebuilding the enum type it binds to by OID.
    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")

    op.execute("ALTER TYPE account_role RENAME TO account_role_old;")
    op.execute(
        "CREATE TYPE account_role AS ENUM "
        "('cash', 'customer_equity', 'position_units', 'position_cost', "
        "'fees_expense', 'dividend_income', 'customer_receivable', "
        "'dividend_receivable', 'realized_gain_loss');"
    )
    op.execute(
        "ALTER TABLE account ALTER COLUMN role TYPE account_role USING role::text::account_role;"
    )
    op.execute("DROP TYPE account_role_old;")

    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _OLD_CONSTRAINT_SQL)
