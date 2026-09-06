"""Internal-state readers shared by `ReconciliationService` (the matching side, S7 §6) and
`CustodianFileSimulatorAdapter` (the baseline-generation side, S7 §9) -- both need "what does
Trueup's own ledger currently say," and duplicating that read independently in each would risk the
two silently drifting on what counts as a position/transaction.

Adapted from `DailyValuationJob._securities_with_positions`'s `Account`/`Posting`/`JournalEntry`
join (S4), grouped per `(customer_id, security_id)` instead of `security_id` alone since S7's match
grain is per-customer (S7 §4), not whole-book.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.core.money import Money, Units
from app.models.identity.customer import Customer
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ops.inbound_event import InboundEvent

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.services.reconciliation.uow import ReconciliationUnitOfWork

CUSTODIAN_OBSERVABLE_ENTRY_TYPES: frozenset[JournalEntryType] = frozenset(
    {
        JournalEntryType.TRADE_BUY,
        JournalEntryType.TRADE_SELL,
        JournalEntryType.DEPOSIT,
        JournalEntryType.WITHDRAWAL,
        JournalEntryType.DIVIDEND,
        JournalEntryType.FEE_ADJUSTMENT,
    }
)
"""S7 §4's "every S1 journal entry that has an external counterpart" -- a correction, split, or
wash-sale adjustment is an internal-only bookkeeping act with no independent custodian-side
transaction id, so those entry types are never expected to have a custodian file counterpart."""


@dataclass(frozen=True, slots=True)
class InternalTransactionSnapshot:
    journal_entry_id: uuid.UUID
    entry_type: JournalEntryType
    customer_id: uuid.UUID | None
    security_id: uuid.UUID | None
    amount_money: Money
    quantity: Units | None
    effective_date: date


def read_internal_positions(
    uow: ReconciliationUnitOfWork, market_date: date
) -> dict[tuple[uuid.UUID, uuid.UUID], Units]:
    """Every nonzero `(customer_id, security_id)` position as of `market_date` (live), across
    every customer -- an admin/worker-role query, deliberately not tenant-scoped, matching
    `DailyValuationJob._securities_with_positions`'s own precedent."""
    statement = (
        select(
            Account.customer_id,
            Account.security_id,
            func.coalesce(func.sum(Posting.quantity_units), 0),
        )
        .join(Posting, Posting.account_id == Account.id)
        .join(JournalEntry, JournalEntry.id == Posting.journal_entry_id)
        .where(
            Account.role == AccountRole.POSITION_UNITS,
            JournalEntry.effective_date <= market_date,
        )
        .group_by(Account.customer_id, Account.security_id)
    )
    rows = uow.session.execute(statement).all()
    return {
        (customer_id, security_id): Units(units)
        for customer_id, security_id, units in rows
        if customer_id is not None and security_id is not None and Units(units) != Units("0")
    }


def read_customer_ids(uow: ReconciliationUnitOfWork) -> set[uuid.UUID]:
    return set(uow.session.execute(select(Customer.id)).scalars().all())


def read_internal_transactions(
    uow: ReconciliationUnitOfWork, market_date: date
) -> dict[str, InternalTransactionSnapshot]:
    """Every custodian-observable journal entry effective on `market_date`, keyed by the
    `inbound_event.source_event_id` it traces back to (S7 §4's match key)."""
    statement = (
        select(JournalEntry, InboundEvent.source_event_id)
        .join(InboundEvent, InboundEvent.id == JournalEntry.source_event_id)
        .where(
            JournalEntry.effective_date == market_date,
            JournalEntry.entry_type.in_(CUSTODIAN_OBSERVABLE_ENTRY_TYPES),
        )
    )
    rows = uow.session.execute(statement).all()
    result: dict[str, InternalTransactionSnapshot] = {}
    for entry, source_event_id in rows:
        postings = uow.postings.for_journal_entry(entry.id)
        customer_id = next((p.customer_id for p in postings if p.customer_id is not None), None)
        amount_total = Money("0.00")
        units_total: Units | None = None
        security_id: uuid.UUID | None = None
        for posting in postings:
            if posting.amount_money is not None:
                amount_total += posting.amount_money
            if posting.quantity_units is not None:
                units_total = (units_total or Units("0")) + posting.quantity_units
                account = uow.accounts.get_by_id(posting.account_id)
                if account is not None:
                    security_id = account.security_id
        result[source_event_id] = InternalTransactionSnapshot(
            journal_entry_id=entry.id,
            entry_type=entry.entry_type,
            customer_id=customer_id,
            security_id=security_id,
            amount_money=amount_total,
            quantity=units_total,
            effective_date=entry.effective_date,
        )
    return result


__all__ = [
    "CUSTODIAN_OBSERVABLE_ENTRY_TYPES",
    "InternalTransactionSnapshot",
    "read_customer_ids",
    "read_internal_positions",
    "read_internal_transactions",
]
