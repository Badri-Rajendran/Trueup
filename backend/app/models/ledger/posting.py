"""`posting` (S1 §3.3) — the legs. Each row moves exactly one dimension on exactly one account.

Two triggers, both bound to this table's own DDL lifecycle (so any path that creates `posting`
via SQLAlchemy metadata -- a test fixture included -- gets the real behaviour, never only what a
migration happens to also state):

- `posting_before_insert` (`BEFORE INSERT`, per-row, synchronous): denormalizes `customer_id` from
  the target account and validates that the non-null leg column matches the account's dimension
  (§3.3). `posting.customer_id` is never written by application code -- the trigger always
  overwrites it from `account.customer_id`, so what the ORM sends for that column is irrelevant.
- `ledger_balance` (`AFTER INSERT OR UPDATE OR DELETE`, `DEFERRABLE INITIALLY DEFERRED`, ADR 17):
  fires once at `COMMIT`, after every leg of a multi-row posting has been written, and raises if a
  journal entry's money postings do not sum to zero (§3.4).

Both are distinct from `PostingService`'s own application-layer zero-sum check (belt-and-suspenders,
matching `BaseRepository`'s append-only guard being one layer above the revoked DB grants).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import DDL, CheckConstraint, ForeignKey, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.money import Money, MoneyType, Units, UnitsType
from app.core.repository import BaseRepository
from app.models.base import Base

if TYPE_CHECKING:
    from app.core.uow import UnitOfWork


class Posting(Base):
    __tablename__ = "posting"
    __table_args__ = (
        CheckConstraint(
            "(amount_money IS NOT NULL AND quantity_units IS NULL) OR "
            "(amount_money IS NULL AND quantity_units IS NOT NULL)",
            name="exactly_one_dimension",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    journal_entry_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("journal_entry.id"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("account.id"), nullable=False
    )
    # Denormalized from account.customer_id, trigger-set (posting_before_insert below). Never
    # written by application code -- see module docstring.
    customer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    amount_money: Mapped[Money | None] = mapped_column(MoneyType, nullable=True)
    quantity_units: Mapped[Units | None] = mapped_column(UnitsType, nullable=True)


# --- posting_before_insert: denormalization + dimension validation (§3.3) -------------------

_POSTING_BEFORE_INSERT_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION posting_denormalize_and_validate() RETURNS trigger AS $$
    DECLARE
      acct RECORD;
    BEGIN
      SELECT customer_id, dimension INTO acct FROM account WHERE id = NEW.account_id;

      NEW.customer_id := acct.customer_id;

      IF acct.dimension = 'money' AND NEW.quantity_units IS NOT NULL THEN
        RAISE EXCEPTION 'posting.quantity_units set against a money-dimension account (%%)',
          NEW.account_id;
      ELSIF acct.dimension = 'units' AND NEW.amount_money IS NOT NULL THEN
        RAISE EXCEPTION 'posting.amount_money set against a units-dimension account (%%)',
          NEW.account_id;
      END IF;

      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_POSTING_BEFORE_INSERT_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE TRIGGER posting_before_insert
      BEFORE INSERT ON posting
      FOR EACH ROW EXECUTE FUNCTION posting_denormalize_and_validate();
    """
)

# --- ledger_balance: cross-row zero-sum invariant, deferred to COMMIT (§6, ADR 17) -----------

_LEDGER_BALANCE_FUNCTION = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE OR REPLACE FUNCTION check_journal_entry_balance() RETURNS trigger AS $$
    DECLARE
      je_id uuid;
      total NUMERIC(18,4);
    BEGIN
      je_id := COALESCE(NEW.journal_entry_id, OLD.journal_entry_id);
      SELECT COALESCE(SUM(amount_money), 0) INTO total FROM posting WHERE journal_entry_id = je_id;
      IF total <> 0 THEN
        RAISE EXCEPTION 'journal_entry %% postings do not sum to zero (got %%)', je_id, total;
      END IF;
      RETURN NULL;
    END;
    $$ LANGUAGE plpgsql;
    """
)

_LEDGER_BALANCE_TRIGGER = DDL(  # type: ignore[no-untyped-call]
    """
    CREATE CONSTRAINT TRIGGER ledger_balance
      AFTER INSERT OR UPDATE OR DELETE ON posting
      DEFERRABLE INITIALLY DEFERRED
      FOR EACH ROW
      EXECUTE FUNCTION check_journal_entry_balance();
    """
)

for _ddl in (
    _POSTING_BEFORE_INSERT_FUNCTION,
    _POSTING_BEFORE_INSERT_TRIGGER,
    _LEDGER_BALANCE_FUNCTION,
    _LEDGER_BALANCE_TRIGGER,
):
    event.listen(Posting.__table__, "after_create", _ddl)

event.listen(
    Posting.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP TRIGGER IF EXISTS ledger_balance ON posting;"
        "DROP TRIGGER IF EXISTS posting_before_insert ON posting;"
        "DROP FUNCTION IF EXISTS check_journal_entry_balance();"
        "DROP FUNCTION IF EXISTS posting_denormalize_and_validate();"
    ),
)

# --- RLS: role-aware tenant isolation, `posting`'s own policy since its tenant key is
# denormalized rather than native (S1 §3.3, S0 §7.3, ADR 17) ---------------------------------

event.listen(
    Posting.__table__,
    "after_create",
    DDL(  # type: ignore[no-untyped-call]
        """
        ALTER TABLE posting ENABLE ROW LEVEL SECURITY;
        CREATE POLICY tenant_isolation ON posting
        USING (
            current_setting('app.role', true) IN ('adviser', 'admin')
            OR customer_id = NULLIF(current_setting('app.customer_id', true), '')::uuid
        );
        """
    ),
)
event.listen(
    Posting.__table__,
    "before_drop",
    DDL(  # type: ignore[no-untyped-call]
        "DROP POLICY IF EXISTS tenant_isolation ON posting;"
        "ALTER TABLE posting DISABLE ROW LEVEL SECURITY;"
    ),
)

# Append-only enforcement (S1 §6): see journal_entry.py's identical comment.
event.listen(
    Posting.__table__,
    "after_create",
    DDL("REVOKE UPDATE, DELETE ON posting FROM trueup_app, trueup_worker;"),  # type: ignore[no-untyped-call]
)


class PostingRepository(BaseRepository[Posting]):
    append_only = True

    def __init__(self, uow: UnitOfWork) -> None:
        super().__init__(uow, entity=Posting, customer_id_column=Posting.customer_id)

    def for_journal_entry(self, journal_entry_id: uuid.UUID) -> list[Posting]:
        return (
            self.session.query(Posting)
            .filter_by(journal_entry_id=journal_entry_id)
            .all()
        )
