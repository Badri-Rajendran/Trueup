"""make admin_audit_log target_customer_id nullable

Revision ID: 42545d3cedde
Revises: 776c140e220a
Create Date: 2026-09-05 16:44:48.290158

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42545d3cedde'
down_revision: Union[str, Sequence[str], None] = '776c140e220a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Not every audited action has a single-customer target -- e.g. resolving a
    # reconciliation_break with no customer attribution (S7 §5.2). The audit trail
    # (actor/action/payload-hash) still applies; there is simply no customer to index that one
    # row under.
    op.alter_column('admin_audit_log', 'target_customer_id', nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('admin_audit_log', 'target_customer_id', nullable=False)
