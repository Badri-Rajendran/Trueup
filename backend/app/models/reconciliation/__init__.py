"""Reconciliation aggregates (S7) -- the custodian-file import log and the break register.

`ReconciliationUnitOfWork` exposes S7's own two repositories (S0 §5's documented extension
mechanism), the same shape as `LedgerUnitOfWork`/`MarketDataUnitOfWork`/`OpsUnitOfWork`. The
composed `UnitOfWork` `ReconciliationService`/`MorningReconciliationJob`/the admin breaks
controller actually use -- combining this with `LedgerUnitOfWork` (positions/cash) and
`MarketDataUnitOfWork` (the trading calendar) -- lives in `app/services/reconciliation/uow.py`,
matching `ValuationUnitOfWork`'s precedent for the identical shape of problem.
"""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.reconciliation.custodian_file_row import CustodianFileRowRepository
from app.models.reconciliation.reconciliation_break import ReconciliationBreakRepository


class ReconciliationUnitOfWork(UnitOfWork):
    @cached_property
    def custodian_file_rows(self) -> CustodianFileRowRepository:
        return CustodianFileRowRepository(self)

    @cached_property
    def reconciliation_breaks(self) -> ReconciliationBreakRepository:
        return ReconciliationBreakRepository(self)


__all__ = ["ReconciliationUnitOfWork"]
