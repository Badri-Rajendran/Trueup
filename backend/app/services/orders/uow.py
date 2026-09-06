"""Composes `IdentityUnitOfWork`, `LotsUnitOfWork`, and `MarketDataUnitOfWork` with S3's own
repositories."""

from __future__ import annotations

from functools import cached_property

from app.models.marketdata import MarketDataUnitOfWork
from app.models.ops.idempotency_key import IdempotencyKeyRepository
from app.models.orders.approval_hold import ApprovalHoldRepository
from app.models.orders.order import OrderRepository
from app.models.orders.order_event import OrderEventRepository
from app.services.identity.uow import IdentityUnitOfWork
from app.services.lots.uow import LotsUnitOfWork


class OrdersUnitOfWork(IdentityUnitOfWork, LotsUnitOfWork, MarketDataUnitOfWork):
    @cached_property
    def orders(self) -> OrderRepository:
        return OrderRepository(self)

    @cached_property
    def order_events(self) -> OrderEventRepository:
        return OrderEventRepository(self)

    @cached_property
    def approval_holds(self) -> ApprovalHoldRepository:
        return ApprovalHoldRepository(self)

    @cached_property
    def idempotency_keys(self) -> IdempotencyKeyRepository:
        return IdempotencyKeyRepository(self)


__all__ = ["OrdersUnitOfWork"]
