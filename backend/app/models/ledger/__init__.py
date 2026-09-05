"""Ledger & units core aggregates (S1) -- the economic source of truth every later sub-project
reads from."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.ledger.account import AccountRepository
from app.models.ledger.customer_cash_lock import CustomerCashLockRepository
from app.models.ledger.journal_entry import JournalEntryRepository
from app.models.ledger.posting import PostingRepository
from app.models.ledger.settlement_obligation import SettlementObligationRepository


class LedgerUnitOfWork(UnitOfWork):
    """A `UnitOfWork` exposing the repositories S1 owns (S0 §5's documented extension mechanism)."""

    @cached_property
    def accounts(self) -> AccountRepository:
        return AccountRepository(self)

    @cached_property
    def journal_entries(self) -> JournalEntryRepository:
        return JournalEntryRepository(self)

    @cached_property
    def postings(self) -> PostingRepository:
        return PostingRepository(self)

    @cached_property
    def settlement_obligations(self) -> SettlementObligationRepository:
        return SettlementObligationRepository(self)

    @cached_property
    def cash_locks(self) -> CustomerCashLockRepository:
        return CustomerCashLockRepository(self)
