"""`AdminUnitOfWork` — S8's admin surface (`/admin/customers`, `/admin/customers/<id>`,
`/admin/customers/<id>/fees`) reads across S1 (ledger/balance), S2 (customer identity), S4 (market
data, for `ValuationService`), S6 (published snapshots), S7 (reconciliation breaks), and S10
(fees) — so this composes `FeesUnitOfWork` (which already carries `IdentityUnitOfWork` and
`RestatementUnitOfWork`, itself `ValuationUnitOfWork` + `RestatementModelsUnitOfWork`) with S7's
own model-only mixin, the identical multiple-inheritance shape every other cross-aggregate
consumer in this codebase already uses (S0 §5's documented extension mechanism).

Composing `FeesUnitOfWork` rather than duplicating its accessors is what lets
`GET /admin/customers/<id>` call the *same* `ValuationService.value_book` code path
`GET /valuation/balance` does (S8 §6 edge case 4's no-drift requirement) and
`GET /admin/customers/<id>/fees` call the *same* fee-summary assembly `GET /fees` does, on one
`UnitOfWork` rather than two independently-implemented aggregations.
"""

from __future__ import annotations

from app.models.reconciliation import ReconciliationUnitOfWork as ReconciliationModelsUnitOfWork
from app.services.fees.uow import FeesUnitOfWork


class AdminUnitOfWork(FeesUnitOfWork, ReconciliationModelsUnitOfWork):
    pass


__all__ = ["AdminUnitOfWork"]
