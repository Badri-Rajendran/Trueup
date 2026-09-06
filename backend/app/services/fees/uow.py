"""S10's UoW: composes `RestatementUnitOfWork`, `IdentityUnitOfWork`, `OpsUnitOfWork`, and `FeesModelsUnitOfWork`."""

from __future__ import annotations

from app.models.fees import FeesModelsUnitOfWork
from app.models.ops import OpsUnitOfWork
from app.services.identity.uow import IdentityUnitOfWork
from app.services.restatement.uow import RestatementUnitOfWork


class FeesUnitOfWork(
    RestatementUnitOfWork, IdentityUnitOfWork, OpsUnitOfWork, FeesModelsUnitOfWork
):
    pass


__all__ = ["FeesUnitOfWork"]
