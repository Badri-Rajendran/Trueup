"""Query logic shared by more than one `app/services/identity/` service.

Kept separate from any one service module so two independent callers (`DepositService`,
`FundingSummaryService`) can share a single implementation rather than drift apart (see
`deposited_on`'s own docstring).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.money import Money
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.services.identity.funding_uow import FundingUnitOfWork


def deposited_on(uow: FundingUnitOfWork, customer_id: uuid.UUID, *, effective_date: date) -> Money:
    """The single definition of the per-day deposit cap's left-hand side (S2 §5.2 step 2).
    `DepositService.initiate()` enforces against this; `FundingSummaryService` discloses it. Two
    separate implementations would let the disclosed headroom silently drift from what's actually
    enforced."""
    statement = (
        select(func.coalesce(func.sum(Posting.amount_money), 0))
        .join(Account, Account.id == Posting.account_id)
        .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
        .where(
            Posting.customer_id == customer_id,
            Account.role == AccountRole.CASH,
            JournalEntry.entry_type == JournalEntryType.DEPOSIT,
            JournalEntry.effective_date == effective_date,
        )
    )
    total = uow.session.execute(statement).scalar_one()
    return Money(total) if total is not None else Money("0.00")


__all__ = ["deposited_on"]
