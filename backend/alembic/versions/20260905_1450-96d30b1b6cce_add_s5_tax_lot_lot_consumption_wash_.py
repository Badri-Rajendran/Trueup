"""add S5 tax lot, lot consumption, wash sale tables

Revision ID: 96d30b1b6cce
Revises: e07a426f914f
Create Date: 2026-09-05 14:50:41.762357

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import app


# revision identifiers, used by Alembic.
revision: str = '96d30b1b6cce'
down_revision: Union[str, Sequence[str], None] = 'e07a426f914f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('tax_lot',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('security_id', sa.UUID(), nullable=False),
    sa.Column('opening_fill_execution_id', sa.String(length=255), nullable=False),
    sa.Column('quantity_opened', app.core.money.UnitsType(precision=28, scale=6), nullable=False),
    sa.Column('quantity_remaining', app.core.money.UnitsType(precision=28, scale=6), nullable=False),
    sa.Column('original_cost_basis', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('adjusted_basis', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('acquired_at', sa.Date(), nullable=False),
    sa.Column('designation', sa.Enum('unspecified', 'specific', name='lot_designation'), nullable=False),
    sa.Column('designation_window_closes_at', sa.DateTime(timezone=True), nullable=False),
    sa.CheckConstraint('quantity_remaining >= 0', name=op.f('ck_tax_lot_quantity_remaining_non_negative')),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_tax_lot_customer_id_customer')),
    sa.ForeignKeyConstraint(['opening_fill_execution_id'], ['order_event.execution_id'], name=op.f('fk_tax_lot_opening_fill_execution_id_order_event')),
    sa.ForeignKeyConstraint(['security_id'], ['security.id'], name=op.f('fk_tax_lot_security_id_security')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tax_lot')),
    sa.UniqueConstraint('opening_fill_execution_id', name=op.f('uq_tax_lot_opening_fill_execution_id'))
    )
    op.create_table('lot_consumption',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('closing_fill_execution_id', sa.String(length=255), nullable=False),
    sa.Column('tax_lot_id', sa.UUID(), nullable=False),
    sa.Column('quantity_consumed', app.core.money.UnitsType(precision=28, scale=6), nullable=False),
    sa.Column('realized_gain_loss', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('is_provisional', sa.Boolean(), nullable=False),
    sa.Column('sale_date', sa.Date(), nullable=False),
    sa.ForeignKeyConstraint(['closing_fill_execution_id'], ['order_event.execution_id'], name=op.f('fk_lot_consumption_closing_fill_execution_id_order_event')),
    sa.ForeignKeyConstraint(['tax_lot_id'], ['tax_lot.id'], name=op.f('fk_lot_consumption_tax_lot_id_tax_lot')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_lot_consumption'))
    )
    op.create_table('wash_sale_adjustment',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('original_lot_consumption_id', sa.UUID(), nullable=False),
    sa.Column('replacement_tax_lot_id', sa.UUID(), nullable=False),
    sa.Column('disallowed_amount', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('journal_entry_id', sa.UUID(), nullable=False),
    sa.ForeignKeyConstraint(['journal_entry_id'], ['journal_entry.id'], name=op.f('fk_wash_sale_adjustment_journal_entry_id_journal_entry')),
    sa.ForeignKeyConstraint(['original_lot_consumption_id'], ['lot_consumption.id'], name=op.f('fk_wash_sale_adjustment_original_lot_consumption_id_lot_consumption')),
    sa.ForeignKeyConstraint(['replacement_tax_lot_id'], ['tax_lot.id'], name=op.f('fk_wash_sale_adjustment_replacement_tax_lot_id_tax_lot')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_wash_sale_adjustment')),
    sa.UniqueConstraint('original_lot_consumption_id', name='uq_wash_sale_original_consumption')
    )

    # --- RLS: role-aware tenant isolation on `tax_lot` (S0 §7.3, ADR 17) -- `lot_consumption`/
    # `wash_sale_adjustment` carry no customer_id of their own (S5 §3.2/§3.3), matching
    # journal_entry/order_event's precedent: per-customer reads join through `tax_lot`.
    op.execute("""
        ALTER TABLE tax_lot ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON tax_lot
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tax_lot;")
    op.execute("ALTER TABLE tax_lot DISABLE ROW LEVEL SECURITY;")

    op.drop_table('wash_sale_adjustment')
    op.drop_table('lot_consumption')
    op.drop_table('tax_lot')
    sa.Enum(name='lot_designation').drop(op.get_bind(), checkfirst=True)
