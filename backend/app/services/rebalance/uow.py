"""`RebalanceUnitOfWork` — S9 needs `RebalanceModelsUnitOfWork` (`model_portfolio`,
`target_weight`, `customer_model_assignment`), `ValuationUnitOfWork` (S4's `LedgerUnitOfWork` +
`MarketDataUnitOfWork`, for `DriftEvaluationService`'s `ValuationService` + direct `daily_closes`
reads), and `OrdersUnitOfWork` (S3's `OrderService`, the one path a rebalance order is ever
submitted through — S9 §6's "identical to a customer order, no parallel mechanism"). Composes all
three rather than duplicating their repository accessors (S0 §5's extension mechanism), the
identical multiple-inheritance shape `LotsUnitOfWork`/`OrdersUnitOfWork` already establish for the
same kind of cross-aggregate consumer.

`OrdersUnitOfWork` already carries `LedgerUnitOfWork`/`MarketDataUnitOfWork` transitively (via
`LotsUnitOfWork`), so `ValuationUnitOfWork` adds nothing new here beyond the *nominal* type
`ValuationService.__init__(uow: ValuationUnitOfWork)` requires -- without it, passing this
`UnitOfWork` to `ValuationService` would only be structurally compatible, which `mypy --strict`
does not accept for a concrete (non-`Protocol`) parameter type.
"""

from __future__ import annotations

from app.models.rebalance import RebalanceModelsUnitOfWork
from app.services.orders.uow import OrdersUnitOfWork
from app.services.valuation.uow import ValuationUnitOfWork


class RebalanceUnitOfWork(OrdersUnitOfWork, ValuationUnitOfWork, RebalanceModelsUnitOfWork):
    pass


__all__ = ["RebalanceUnitOfWork"]
