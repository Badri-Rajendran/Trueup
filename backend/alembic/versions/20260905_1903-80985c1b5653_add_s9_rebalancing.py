"""add S9 rebalancing

Revision ID: 80985c1b5653
Revises: 9b1c7a4f3d02
Create Date: 2026-09-05 19:03:58.519616

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '80985c1b5653'
down_revision: Union[str, Sequence[str], None] = '9b1c7a4f3d02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Autogenerate also proposed unrelated drift (bank_link, kyc_session, chat_message default); excluded here.


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('model_portfolio',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_model_portfolio'))
    )
    op.create_table('target_weight',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('model_portfolio_id', sa.UUID(), nullable=False),
    sa.Column('security_id', sa.UUID(), nullable=False),
    sa.Column('weight_pct', sa.Numeric(precision=5, scale=4), nullable=False),
    sa.ForeignKeyConstraint(['model_portfolio_id'], ['model_portfolio.id'], name=op.f('fk_target_weight_model_portfolio_id_model_portfolio')),
    sa.ForeignKeyConstraint(['security_id'], ['security.id'], name=op.f('fk_target_weight_security_id_security')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_target_weight')),
    sa.UniqueConstraint('model_portfolio_id', 'security_id', name='uq_target_weight_model_security')
    )
    op.create_table('customer_model_assignment',
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('model_portfolio_id', sa.UUID(), nullable=False),
    sa.Column('assigned_at', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_customer_model_assignment_customer_id_customer')),
    sa.ForeignKeyConstraint(['model_portfolio_id'], ['model_portfolio.id'], name=op.f('fk_customer_model_assignment_model_portfolio_id_model_portfolio')),
    sa.PrimaryKeyConstraint('customer_id', name=op.f('pk_customer_model_assignment'))
    )

    # RLS tenant isolation on customer_model_assignment (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE customer_model_assignment ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON customer_model_assignment
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # target_weight_sum: cross-row sum-to-one invariant, deferred to COMMIT (S9 §3.2).
    op.execute("""
        CREATE OR REPLACE FUNCTION check_target_weight_sum() RETURNS trigger AS $$
        DECLARE
          mp_id uuid;
          total NUMERIC(5,4);
        BEGIN
          mp_id := COALESCE(NEW.model_portfolio_id, OLD.model_portfolio_id);
          SELECT COALESCE(SUM(weight_pct), 0) INTO total FROM target_weight WHERE model_portfolio_id = mp_id;
          IF total <> 1 THEN
            RAISE EXCEPTION 'model_portfolio % target weights do not sum to 1.0 (got %)', mp_id, total;
          END IF;
          RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE CONSTRAINT TRIGGER target_weight_sum
          AFTER INSERT OR UPDATE OR DELETE ON target_weight
          DEFERRABLE INITIALLY DEFERRED
          FOR EACH ROW
          EXECUTE FUNCTION check_target_weight_sum();
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP TRIGGER IF EXISTS target_weight_sum ON target_weight;")
    op.execute("DROP FUNCTION IF EXISTS check_target_weight_sum();")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON customer_model_assignment;")
    op.execute("ALTER TABLE customer_model_assignment DISABLE ROW LEVEL SECURITY;")

    op.drop_table('customer_model_assignment')
    op.drop_table('target_weight')
    op.drop_table('model_portfolio')
