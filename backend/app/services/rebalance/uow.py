"""S9 UoW: composes `OrdersUnitOfWork`, `ValuationUnitOfWork`, and `RebalanceModelsUnitOfWork`."""

from __future__ import annotations

from app.models.rebalance import RebalanceModelsUnitOfWork
from app.services.orders.uow import OrdersUnitOfWork
from app.services.valuation.uow import ValuationUnitOfWork


class RebalanceUnitOfWork(OrdersUnitOfWork, ValuationUnitOfWork, RebalanceModelsUnitOfWork):
    pass


__all__ = ["RebalanceUnitOfWork"]
