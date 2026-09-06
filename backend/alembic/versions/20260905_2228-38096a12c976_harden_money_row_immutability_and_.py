"""harden money-row immutability and idempotency_key rls

Revision ID: 38096a12c976
Revises: 44100b4c0cae
Create Date: 2026-09-05 22:28:16.626996

F12/I3/I9 fixes (S0 §10.1 audit). Two independent gaps, both against the automatic-fail rule
"UPDATE or DELETE on money rows. Anywhere. Ever." and S0 §7.3's tenant-isolation requirement:

- The entire S5 migration (tax_lot/lot_consumption/wash_sale_adjustment) shipped with no REVOKE
  statements at all, unlike every other money-bearing table in the schema. `tax_lot`/
  `lot_consumption` are documented mutable projections (UPDATE stays legitimate) but must never be
  deleted; `wash_sale_adjustment` is itself an immutable correction record and gets the full
  REVOKE UPDATE, DELETE every other immutable ledger table has. `approval_hold` (S3),
  `high_water_mark` and `fee_charge` (S10) had the same DELETE gap -- `fee_charge`'s own
  `as_published_watermark` column is already protected by a trigger, but the row itself was never
  protected from deletion.
- `idempotency_key` stores a customer's cached response body (financial PII) and is tenant-scoped
  by `customer_id`, but was the only such table in the schema with no Row-Level Security policy at
  all -- every one of its 23 siblings has one. Added the identical `tenant_isolation` predicate
  every other table uses.

Each corresponding model file (`app/models/...`) now also carries the equivalent
`event.listen(..., "after_create", DDL(...))` hook, matching this codebase's established pattern
of applying the same grant/policy DDL whether a table is created by this migration or by
SQLAlchemy metadata directly (the test suite's own path) -- see `journal_entry.py`'s identical
precedent, cited in its own comment.
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
