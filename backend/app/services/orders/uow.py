"""`OrdersUnitOfWork` — composes `IdentityUnitOfWork` (KYC/account-approval gate checks, S3 §7
case 2), `LedgerUnitOfWork` (S1: a fill posts a `trade_buy`/`trade_sell` entry, and a hold
acquires the same per-customer cash-lock row a withdrawal or fee charge would, foundation spec
§10 case 1; S5 adds `tax_lots`/`lot_consumptions`/`wash_sale_adjustments` to this same mixin),
`OpsUnitOfWork` (enqueueing the `submit_order_to_broker` outbox task, S3 §4; also `inbound_events`,
for S5's synthesized-event-per-posting pattern), and `MarketDataUnitOfWork` (S5's fill-integration
needs `calendar_cache` for the `MarketClock` a trade's T+1 settlement/designation-window
computation requires -- the same reason `ValuationUnitOfWork` composes it) onto one transaction
boundary, plus S3's own `orders`/`order_events`/`approval_holds`/`idempotency_keys` repositories.

The identical composed-via-multiple-inheritance pattern `FundingUnitOfWork` (S2) already
establishes for the same shape of problem (S0 §5's documented extension mechanism) -- and lives
here, in `app/services/`, rather than `app/models/orders/`, for the same reason
`FundingUnitOfWork` does: it depends on `IdentityUnitOfWork`, which is itself a services-layer
module, and `app/models/` may not import `app/services/` (S0 §3).
"""

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
