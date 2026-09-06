"""One transaction boundary spanning identity, ledger, and ops repositories for S2's funding flows.

Composes `IdentityUnitOfWork`, `LedgerUnitOfWork`, and `OpsUnitOfWork` via multiple inheritance
(S0 §5), and adds idempotency-key/order/approval-hold repos for the same commit.
"""

from __future__ import annotations

from functools import cached_property

from app.models.ledger import LedgerUnitOfWork
from app.models.ops import OpsUnitOfWork
from app.models.ops.idempotency_key import IdempotencyKeyRepository
from app.models.orders.approval_hold import ApprovalHoldRepository
from app.models.orders.order import OrderRepository
from app.services.identity.uow import IdentityUnitOfWork


class FundingUnitOfWork(IdentityUnitOfWork, LedgerUnitOfWork, OpsUnitOfWork):
    @cached_property
    def idempotency_keys(self) -> IdempotencyKeyRepository:
        return IdempotencyKeyRepository(self)

    @cached_property
    def orders(self) -> OrderRepository:
        """S3's order repo, added here so `OrderHoldsProvider` can be wired in without a new UoW class."""
        return OrderRepository(self)

    @cached_property
    def approval_holds(self) -> ApprovalHoldRepository:
        return ApprovalHoldRepository(self)
