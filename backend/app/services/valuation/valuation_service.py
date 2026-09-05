"""`ValuationService` (S4 §4) — values a customer's whole book against closing prices.

`account`/`posting`/`journal_entry` are S1's (read here, never written — this service opens no
`UnitOfWork` write path onto the ledger). A position's quantity "as of" a date is the sum of every
`quantity_units` posting on that customer's `position_units:<security>` account whose journal
entry's `effective_date` is on or before that date — corrections post *additional* legs rather than
mutating history (ADR 1), so summing is always correct, live, with no special-casing for a
superseded entry. Cash is summed the same way over `cash`-role accounts.

This is deliberately **not** `CashPolicyService.settled_cash`: that function excludes cash pending
settlement confirmation, which is the right rule for a *withdraw* decision (FR-13) but wrong here —
S1 §4 is explicit that the ledger posts the *economic* fact immediately at trade/deposit time, and
whole-book valuation (FR-14) is exactly that economic fact, not a withdrawability gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from sqlalchemy import func, select

from app.core.money import Money, Units
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.services.valuation.uow import ValuationUnitOfWork

Completeness = Literal["complete", "partial"]


@dataclass(frozen=True, slots=True)
class BookValuation:
    """S4 §4's return shape. `completeness` must survive to every consumer (S8's balance screen,
    S11's chat assistant) — never presented as a whole valuation when it is partial (NFR-6)."""

    total_value: Money
    as_of_date: date
    completeness: Completeness


class ValuationService:
    def __init__(self, uow: ValuationUnitOfWork) -> None:
        self._uow = uow

    def value_book(self, customer_id: uuid.UUID, as_of_date: date) -> BookValuation:
        total_value = self._cash_balance(customer_id, as_of_date)
        completeness: Completeness = "complete"

        for security_id, units in self._position_units(customer_id, as_of_date):
            if units == Units("0"):
                continue
            close = self._uow.daily_closes.latest_confirmed(
                security_id=security_id, market_date=as_of_date
            )
            if close is None:
                # FR-15: never substitute a prior day's close silently — this security's
                # contribution is simply omitted, and the whole book is flagged partial.
                completeness = "partial"
                continue
            total_value += units * close.close_price

        return BookValuation(
            total_value=total_value, as_of_date=as_of_date, completeness=completeness
        )

    def _position_units(
        self, customer_id: uuid.UUID, as_of_date: date
    ) -> list[tuple[uuid.UUID, Units]]:
        statement = (
            select(Account.security_id, func.coalesce(func.sum(Posting.quantity_units), 0))
            .join(Posting, Posting.account_id == Account.id)
            .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.POSITION_UNITS,
                JournalEntry.effective_date <= as_of_date,
            )
            .group_by(Account.security_id)
        )
        rows = self._uow.session.execute(statement).all()
        return [(security_id, units) for security_id, units in rows if security_id is not None]

    def _cash_balance(self, customer_id: uuid.UUID, as_of_date: date) -> Money:
        statement = (
            select(func.coalesce(func.sum(Posting.amount_money), 0))
            .join(Account, Account.id == Posting.account_id)
            .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
            .where(
                Posting.customer_id == customer_id,
                Account.role == AccountRole.CASH,
                JournalEntry.effective_date <= as_of_date,
            )
        )
        value = self._uow.session.execute(statement).scalar_one()
        return value if value is not None else Money("0.00")


__all__ = ["BookValuation", "Completeness", "ValuationService"]
