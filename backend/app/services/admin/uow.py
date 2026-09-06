"""Admin surface UoW (S8): composes `FeesUnitOfWork` with S7's reconciliation mixin."""

from __future__ import annotations

from app.models.reconciliation import ReconciliationUnitOfWork as ReconciliationModelsUnitOfWork
from app.services.fees.uow import FeesUnitOfWork


class AdminUnitOfWork(FeesUnitOfWork, ReconciliationModelsUnitOfWork):
    pass


__all__ = ["AdminUnitOfWork"]
