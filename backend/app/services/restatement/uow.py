"""`RestatementUnitOfWork` — S6 spans S1's ledger, S4's market data (`ValuationUnitOfWork` already
composes both), and its own `published_snapshot`/`restatement_event` repositories
(`RestatementModelsUnitOfWork`). Composes all three rather than duplicating their repository
accessors (S0 §5's extension mechanism), the identical shape `LotsUnitOfWork`/`OrdersUnitOfWork`
already use for the same kind of cross-aggregate consumer."""

from __future__ import annotations

from app.models.restatement import RestatementModelsUnitOfWork
from app.services.valuation.uow import ValuationUnitOfWork


class RestatementUnitOfWork(ValuationUnitOfWork, RestatementModelsUnitOfWork):
    pass


__all__ = ["RestatementUnitOfWork"]
