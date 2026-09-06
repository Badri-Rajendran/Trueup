"""UoW for S7: composes reconciliation, ledger, market data, ops, and restatement mixins."""

from __future__ import annotations

from app.models import reconciliation as _reconciliation_models
from app.models.ledger import LedgerUnitOfWork
from app.models.marketdata import MarketDataUnitOfWork
from app.models.ops import OpsUnitOfWork
from app.models.restatement import RestatementModelsUnitOfWork


class ReconciliationUnitOfWork(
    _reconciliation_models.ReconciliationUnitOfWork,
    LedgerUnitOfWork,
    MarketDataUnitOfWork,
    OpsUnitOfWork,
    RestatementModelsUnitOfWork,
):
    pass


__all__ = ["ReconciliationUnitOfWork"]
