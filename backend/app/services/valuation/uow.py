"""`ValuationUnitOfWork` — S4 spans two aggregates (S1's ledger, for positions and cash; S4's own
market data), so this composes both domain mixins rather than duplicating their repository
accessors (S0 §5's extension mechanism, applied to a cross-aggregate consumer)."""

from __future__ import annotations

from app.models.ledger import LedgerUnitOfWork
from app.models.marketdata import MarketDataUnitOfWork


class ValuationUnitOfWork(LedgerUnitOfWork, MarketDataUnitOfWork):
    pass
