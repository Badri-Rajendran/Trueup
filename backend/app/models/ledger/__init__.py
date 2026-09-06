"""Ledger & units core aggregates (S1) -- the economic source of truth every later sub-project
reads from."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.ledger.account import AccountRepository
from app.models.ledger.customer_cash_lock import CustomerCashLockRepository
from app.models.ledger.journal_entry import JournalEntryRepository
from app.models.ledger.lot_consumption import LotConsumptionRepository
from app.models.ledger.posting import PostingRepository
from app.models.ledger.settlement_obligation import SettlementObligationRepository
from app.models.ledger.tax_lot import TaxLotRepository
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustmentRepository


class LedgerUnitOfWork(UnitOfWork):
    """`UnitOfWork` exposing the repositories S1 (and S5's tax-lot tables) owns (S0 §5)."""

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

    @cached_property
    def tax_lots(self) -> TaxLotRepository:
        return TaxLotRepository(self)

    @cached_property
    def lot_consumptions(self) -> LotConsumptionRepository:
        return LotConsumptionRepository(self)

    @cached_property
    def wash_sale_adjustments(self) -> WashSaleAdjustmentRepository:
        return WashSaleAdjustmentRepository(self)
