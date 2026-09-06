"""`LotsUnitOfWork` — S5 needs `LedgerUnitOfWork` (accounts, postings, `tax_lots`/
`lot_consumptions`/`wash_sale_adjustments`) and `OpsUnitOfWork` (`inbound_events`, for the
synthesized-event-per-posting pattern `DepositService`/`WithdrawalService` already establish).
Composes both rather than duplicating their repository accessors (S0 §5's extension mechanism),
the identical shape `ValuationUnitOfWork` (S4) already uses for the same kind of cross-aggregate
consumer.

`MarketDataUnitOfWork` and `RestatementModelsUnitOfWork` (S6) are composed here too:
`WashSaleService` and `CorporateActionService` call `RestatementService.restate()` inline, in the
same transaction as the correcting entry they just posted (`app.models.restatement`'s own module
docstring explains why that must be the *same* `UnitOfWork`, not a fresh one). `OrdersUnitOfWork`
gets both transitively, being a `LotsUnitOfWork` itself -- no other file needs to change for the
real, already-wired wash-sale trigger site to work.

`FeesModelsUnitOfWork` (S10) is composed here too, additively: S10's `RestatementService` hook
(`fee_disclosure_checker`) needs `.fee_charges`/`.fee_restatement_disclosures` on the *same*
`UnitOfWork` `WashSaleService`/`CorporateActionService` already hold, for the identical
same-transaction reason as the two mixins above -- not a second `UnitOfWork` instance, and not a
`Protocol` widened to force every other structural implementer to grow these accessors too."""

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
