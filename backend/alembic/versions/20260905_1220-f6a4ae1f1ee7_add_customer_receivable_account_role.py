"""add customer_receivable account role

Revision ID: f6a4ae1f1ee7
Revises: a9f60402b7a1
Create Date: 2026-09-05 12:20:13.375239

S1 §3.1's `role` enum is explicitly extensible; this is S2's first extension (FR-6, S2 §5.2 step
4): a bounced deposit whose cash was already invested leaves a debt the customer owes, tracked as
a `customer_receivable` account (dimension `money`, same as every other money-role account).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6a4ae1f1ee7'
down_revision: Union[str, Sequence[str], None] = 'a9f60402b7a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CONSTRAINT_SQL = (
    "(role = 'cash' AND dimension = 'money') OR "
    "(role = 'customer_equity' AND dimension = 'money') OR "
    "(role = 'position_units' AND dimension = 'units') OR "
    "(role = 'position_cost' AND dimension = 'money') OR "
    "(role = 'fees_expense' AND dimension = 'money') OR "
    "(role = 'dividend_income' AND dimension = 'money')"
)
_NEW_CONSTRAINT_SQL = _OLD_CONSTRAINT_SQL + " OR (role = 'customer_receivable' AND dimension = 'money')"


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot be used in the same transaction that also references the new
    # value (Postgres restriction) -- autocommit_block() runs it in its own committed transaction so
    # the CHECK constraint below, which does reference it, is safe.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'customer_receivable';")

    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")
    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _NEW_CONSTRAINT_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    # The CHECK constraint must be dropped *before* the type rebuild below, and only recreated
    # *after* it: Postgres binds a CHECK constraint's literals to the column's enum type by OID at
    # creation time, so recreating it against the old (7-value) type first and only then rebuilding
    # the column's type underneath it raises "operator does not exist: account_role =
    # account_role_old" -- the constraint's own compiled literals still point at the type being
    # renamed away.
    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")

    # Postgres has no ALTER TYPE ... DROP VALUE -- rebuild the enum type without it. Only safe when
    # no row currently uses the value being removed (true for a clean downgrade with no
    # customer_receivable accounts; S2's own data would need migrating off this role first in a
    # real rollback, same caveat any enum-value removal carries).
    op.execute("ALTER TYPE account_role RENAME TO account_role_old;")
    op.execute(
        "CREATE TYPE account_role AS ENUM "
        "('cash', 'customer_equity', 'position_units', 'position_cost', "
        "'fees_expense', 'dividend_income');"
    )
    op.execute(
        "ALTER TABLE account ALTER COLUMN role TYPE account_role USING role::text::account_role;"
    )
    op.execute("DROP TYPE account_role_old;")

    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _OLD_CONSTRAINT_SQL)
