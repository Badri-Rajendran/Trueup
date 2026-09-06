"""`ReconciliationUnitOfWork` — S7 spans five aggregates: its own (`custodian_file_row`/
`reconciliation_break`), S1's ledger (positions/cash to compare against, and `tax_lots` for
`inject_corrected_price`'s per-customer fan-out), S0's ops spine (`inbound_events`, to synthesize
the event `RestatementService.restate()` requires a `source_event_id` for), S4's market data (the
trading calendar for the holiday short-circuit, S7 §6/ADR 12, plus `sub_period_returns`), and S6's
restatement aggregate (`published_snapshots`/`restatement_events`, via
`RestatementModelsUnitOfWork`, so `inject_corrected_price` can call `RestatementService.restate()`
in the *same* transaction as its `daily_close` write, per restatement-engineer's own
`RestatementCapableUnitOfWork` contract) — composed via multiple inheritance, the identical pattern
`ValuationUnitOfWork`/`LotsUnitOfWork` already establish for the same shape of problem (S0 §5's
documented extension mechanism).

Named identically to `app.models.reconciliation.ReconciliationUnitOfWork` on purpose (matching
that module's own aggregate-only mixin name) — every real caller imports this module's class, not
that one directly, the same way nothing outside `app/services/orders/uow.py` imports
`MarketDataUnitOfWork` expecting `OrdersUnitOfWork`'s full repository surface.
"""

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
