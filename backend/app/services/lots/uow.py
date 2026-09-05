"""`LotsUnitOfWork` — S5 needs `LedgerUnitOfWork` (accounts, postings, `tax_lots`/
`lot_consumptions`/`wash_sale_adjustments`) and `OpsUnitOfWork` (`inbound_events`, for the
synthesized-event-per-posting pattern `DepositService`/`WithdrawalService` already establish).
Composes both rather than duplicating their repository accessors (S0 §5's extension mechanism),
the identical shape `ValuationUnitOfWork` (S4) already uses for the same kind of cross-aggregate
consumer."""

from __future__ import annotations

from app.models.ledger import LedgerUnitOfWork
from app.models.ops import OpsUnitOfWork


class LotsUnitOfWork(LedgerUnitOfWork, OpsUnitOfWork):
    pass


__all__ = ["LotsUnitOfWork"]
