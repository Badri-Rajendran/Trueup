"""Restatement aggregates (S6) — `published_snapshot` and `restatement_event`.

`RestatementModelsUnitOfWork` is the same shape as `MarketDataUnitOfWork`/`LedgerUnitOfWork`/
`OpsUnitOfWork`: a thin models-layer mixin, meant to be composed by more than one services-layer
`UnitOfWork` (S0 §5's documented extension mechanism). Two composers need it for real:

- `app.services.restatement.uow.RestatementUnitOfWork` -- `SnapshotService`/the statements API.
- `app.services.lots.uow.LotsUnitOfWork` -- `RestatementService.restate()` is called synchronously,
  inline, from `WashSaleService`/`CorporateActionService` (S6 §4's real trigger sites), and must
  see their not-yet-committed postings in the *same* transaction (a fresh `UnitOfWork` opened for
  the restatement would read a stale, pre-correction ledger). `LotsUnitOfWork` composing this
  mixin directly -- rather than `RestatementService` requiring its own dedicated `UnitOfWork` type
  -- is what makes that possible without widening `PostingService`'s or any ledger-writing
  service's own dependencies (root `CLAUDE.md`'s KISS/layering rule); `OrdersUnitOfWork` gets it
  for free transitively, being a `LotsUnitOfWork` itself.
"""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.restatement.published_snapshot import PublishedSnapshotRepository
from app.models.restatement.restatement_event import RestatementEventRepository


class RestatementModelsUnitOfWork(UnitOfWork):
    @cached_property
    def published_snapshots(self) -> PublishedSnapshotRepository:
        return PublishedSnapshotRepository(self)

    @cached_property
    def restatement_events(self) -> RestatementEventRepository:
        return RestatementEventRepository(self)


__all__ = ["RestatementModelsUnitOfWork"]
