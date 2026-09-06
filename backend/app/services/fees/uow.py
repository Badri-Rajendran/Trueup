"""`FeesUnitOfWork` — S10 spans S1's ledger, S4's TWR/valuation, S6's restatement machinery
(`SnapshotService.publish`/`PublishedSnapshotRepository` for the fee-charge watermark lock, and the
`RestatementCapableUnitOfWork` shape `RestatementService` needs for its own S10 hook), S2's identity
(the customer's email, for provisioning a Stripe customer), and its own `FeesModelsUnitOfWork`.
Composes rather than duplicates accessors, the same extension mechanism
`RebalanceUnitOfWork`/`RestatementUnitOfWork` already use for a cross-aggregate consumer.
"""

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
