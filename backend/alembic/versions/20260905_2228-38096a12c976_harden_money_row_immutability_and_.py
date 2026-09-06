"""harden money-row immutability and idempotency_key rls

Revision ID: 38096a12c976
Revises: 44100b4c0cae
Create Date: 2026-09-05 22:28:16.626996

F12/I3/I9 fixes (S0 §10.1 audit): revoke missing DELETE grants on money rows and add RLS to
idempotency_key, which had none.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '38096a12c976'
down_revision: Union[str, Sequence[str], None] = '44100b4c0cae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("REVOKE DELETE ON tax_lot FROM trueup_app, trueup_worker;")
    op.execute("REVOKE DELETE ON lot_consumption FROM trueup_app, trueup_worker;")
    op.execute("REVOKE UPDATE, DELETE ON wash_sale_adjustment FROM trueup_app, trueup_worker;")
    op.execute("REVOKE DELETE ON approval_hold FROM trueup_app, trueup_worker;")
    op.execute("REVOKE DELETE ON high_water_mark FROM trueup_app, trueup_worker;")
    op.execute("REVOKE DELETE ON fee_charge FROM trueup_app, trueup_worker;")
    op.execute(
        """
        ALTER TABLE idempotency_key ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON idempotency_key
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON idempotency_key;")
    op.execute("ALTER TABLE idempotency_key DISABLE ROW LEVEL SECURITY;")
    op.execute("GRANT DELETE ON fee_charge TO trueup_app, trueup_worker;")
    op.execute("GRANT DELETE ON high_water_mark TO trueup_app, trueup_worker;")
    op.execute("GRANT DELETE ON approval_hold TO trueup_app, trueup_worker;")
    op.execute("GRANT UPDATE, DELETE ON wash_sale_adjustment TO trueup_app, trueup_worker;")
    op.execute("GRANT DELETE ON lot_consumption TO trueup_app, trueup_worker;")
    op.execute("GRANT DELETE ON tax_lot TO trueup_app, trueup_worker;")
