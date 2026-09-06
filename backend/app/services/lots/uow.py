"""S5 UoW: composes ledger, ops, market data, restatement, and fees mixins for the same-transaction
requirements of `WashSaleService`/`CorporateActionService`."""

from __future__ import annotations

from app.models.fees import FeesModelsUnitOfWork
from app.models.ledger import LedgerUnitOfWork
from app.models.marketdata import MarketDataUnitOfWork
from app.models.ops import OpsUnitOfWork
from app.models.restatement import RestatementModelsUnitOfWork


class LotsUnitOfWork(
    LedgerUnitOfWork,
    OpsUnitOfWork,
    MarketDataUnitOfWork,
    RestatementModelsUnitOfWork,
    FeesModelsUnitOfWork,
):
    pass


__all__ = ["LotsUnitOfWork"]
