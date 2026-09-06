"""add S5 tax lot account roles and journal entry type

Revision ID: e07a426f914f
Revises: 5443b4a0f421
Create Date: 2026-09-05 13:00:00.000000

S1 §3.1's `role` enum and §3.2's `entry_type` enum are both explicitly extensible; this is S5's
extension (FR-21/FR-23, ADR 11): `dividend_receivable`/`realized_gain_loss` (dimension `money`,
same as every other money-role account) plus the `wash_sale_adjustment` journal entry type.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e07a426f914f'
down_revision: Union[str, Sequence[str], None] = '5443b4a0f421'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_CONSTRAINT_SQL = (
    "(role = 'cash' AND dimension = 'money') OR "
    "(role = 'customer_equity' AND dimension = 'money') OR "
    "(role = 'position_units' AND dimension = 'units') OR "
    "(role = 'position_cost' AND dimension = 'money') OR "
    "(role = 'fees_expense' AND dimension = 'money') OR "
    "(role = 'dividend_income' AND dimension = 'money') OR "
    "(role = 'customer_receivable' AND dimension = 'money')"
)
_NEW_CONSTRAINT_SQL = (
    _OLD_CONSTRAINT_SQL
    + " OR (role = 'dividend_receivable' AND dimension = 'money')"
    + " OR (role = 'realized_gain_loss' AND dimension = 'money')"
)


def upgrade() -> None:
    """Upgrade schema."""
    # ALTER TYPE ... ADD VALUE cannot be used in the same transaction that also references the new
    # value (Postgres restriction) -- autocommit_block() runs each in its own committed transaction
    # so the CHECK constraint below, which does reference the new account_role values, is safe.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'dividend_receivable';")
        op.execute("ALTER TYPE account_role ADD VALUE IF NOT EXISTS 'realized_gain_loss';")
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE journal_entry_type ADD VALUE IF NOT EXISTS 'wash_sale_adjustment';"
        )

    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")
    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _NEW_CONSTRAINT_SQL)


def downgrade() -> None:
    """Downgrade schema."""
    # The CHECK constraint must be dropped *before* the type rebuild below, and only recreated
    # *after* it -- same ordering reason as f6a4ae1f1ee7's downgrade (Postgres binds a CHECK
    # constraint's compiled literals to the column's enum type by OID at creation time).
    op.drop_constraint(op.f("ck_account_role_dimension"), "account", type_="check")

    # Postgres has no ALTER TYPE ... DROP VALUE -- rebuild both enum types without the added
    # values. Only safe when no row currently uses them (true for a clean downgrade with no S5
    # data yet), same caveat any enum-value removal carries.
    op.execute("ALTER TYPE account_role RENAME TO account_role_old;")
    op.execute(
        "CREATE TYPE account_role AS ENUM "
        "('cash', 'customer_equity', 'position_units', 'position_cost', "
        "'fees_expense', 'dividend_income', 'customer_receivable');"
    )
    op.execute(
        "ALTER TABLE account ALTER COLUMN role TYPE account_role USING role::text::account_role;"
    )
    op.execute("DROP TYPE account_role_old;")

    op.execute("ALTER TYPE journal_entry_type RENAME TO journal_entry_type_old;")
    op.execute(
        "CREATE TYPE journal_entry_type AS ENUM "
        "('trade_buy', 'trade_sell', 'deposit', 'withdrawal', 'dividend', 'split', "
        "'fee_adjustment', 'correction');"
    )
    op.execute(
        "ALTER TABLE journal_entry ALTER COLUMN entry_type TYPE journal_entry_type "
        "USING entry_type::text::journal_entry_type;"
    )
    op.execute("DROP TYPE journal_entry_type_old;")

    op.create_check_constraint(op.f("ck_account_role_dimension"), "account", _OLD_CONSTRAINT_SQL)
