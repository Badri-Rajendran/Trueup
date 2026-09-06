"""add S3 orders and custody

Revision ID: 5443b4a0f421
Revises: 263eb7564b1d
Create Date: 2026-09-05 12:40:26.791561

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import app


# revision identifiers, used by Alembic.
revision: str = '5443b4a0f421'
down_revision: Union[str, Sequence[str], None] = '263eb7564b1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('order',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('security_id', sa.UUID(), nullable=False),
    sa.Column('side', sa.Enum('buy', 'sell', name='order_side'), nullable=False),
    sa.Column('quantity_requested', app.core.money.UnitsType(precision=28, scale=6), nullable=False),
    sa.Column('status', sa.Enum('draft', 'awaiting_approval', 'approved', 'submitted', 'accepted', 'partially_filled', 'filled', 'rejected', 'canceled', 'expired', name='order_status'), nullable=False),
    sa.Column('filled_quantity', app.core.money.UnitsType(precision=28, scale=6), nullable=False),
    sa.Column('average_fill_price', app.core.money.PriceType(precision=18, scale=6), nullable=True),
    sa.Column('client_order_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_order_customer_id_customer')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order')),
    sa.UniqueConstraint('client_order_id', name=op.f('uq_order_client_order_id'))
    )
    op.create_table('order_event',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('seq', sa.BigInteger(), nullable=False),
    sa.Column('event_type', sa.Enum('submitted', 'accepted', 'fill', 'rejected', 'canceled', 'expired', name='order_event_type'), nullable=False),
    sa.Column('execution_id', sa.String(length=255), nullable=True),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['order_id'], ['order.id'], name=op.f('fk_order_event_order_id_order')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_order_event')),
    sa.UniqueConstraint('execution_id', name=op.f('uq_order_event_execution_id')),
    sa.UniqueConstraint('order_id', 'seq', name=op.f('uq_order_event_order_id_seq'))
    )
    op.create_table('approval_hold',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('order_id', sa.UUID(), nullable=False),
    sa.Column('customer_id', sa.UUID(), nullable=False),
    sa.Column('amount_money', app.core.money.MoneyType(precision=18, scale=4), nullable=False),
    sa.Column('status', sa.Enum('active', 'released', name='approval_hold_status'), nullable=False),
    sa.Column('released_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('release_reason', sa.Enum('approved_and_submitted', 'rejected', 'canceled', 'expired', name='approval_hold_release_reason'), nullable=True),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.id'], name=op.f('fk_approval_hold_customer_id_customer')),
    sa.ForeignKeyConstraint(['order_id'], ['order.id'], name=op.f('fk_approval_hold_order_id_order')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approval_hold')),
    sa.UniqueConstraint('order_id', name=op.f('uq_approval_hold_order_id'))
    )

    # RLS tenant isolation on `order`/`approval_hold` (S0 §7.3, ADR 17).
    op.execute("""
        ALTER TABLE "order" ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON "order"
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );

        ALTER TABLE approval_hold ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON approval_hold
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
    """)

    # Append-only enforcement: no UPDATE/DELETE grant for order_event (ADR 7).
    op.execute("""
        REVOKE UPDATE, DELETE ON order_event FROM trueup_app, trueup_worker;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON approval_hold;")
    op.execute("ALTER TABLE approval_hold DISABLE ROW LEVEL SECURITY;")
    op.execute('DROP POLICY IF EXISTS tenant_isolation ON "order";')
    op.execute('ALTER TABLE "order" DISABLE ROW LEVEL SECURITY;')

    op.drop_table('approval_hold')
    op.drop_table('order_event')
    op.drop_table('order')
    sa.Enum(name='approval_hold_release_reason').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='approval_hold_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='order_event_type').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='order_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='order_side').drop(op.get_bind(), checkfirst=True)
