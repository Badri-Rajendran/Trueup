"""`FundingUnitOfWork` — one transaction boundary spanning identity (`customer`/`kyc_session`/
`bank_link`), ledger (`account`/`journal_entry`/`posting`/`settlement_obligation`/
`customer_cash_lock`), and ops (`inbound_event`/`idempotency_key`) repositories.

S2's funding flows (`DepositService`/`WithdrawalService`/`AccountApprovalService`) need all three in
one `UnitOfWork`, per S0 §5's "exactly one commit point per operation": checking `kyc_status`/
`account_approval_status`/`bank_link.status` (identity), posting a journal entry plus a settlement
obligation (ledger), and recording the `inbound_event` each traces back to (S1 §3.2's "every journal
entry traces back to exactly one inbound_event") must succeed or fail together, atomically. A
customer-initiated deposit/withdrawal has no incoming webhook to intake -- unlike a provider verdict
-- so `DepositService`/`WithdrawalService` record their own `inbound_event` row directly (source
`plaid`, `signature_verified=True` since it is server-originated, not externally signed) rather than
going through `EventIntakeService`, which exists for signature-gated *inbound* provider calls only.

Idempotency (S0 §8): `.idempotency_keys` is added here, not resolved via `app.core.idempotency`'s
process-wide `IdempotencyStore` resolver -- that resolver's lifecycle (when a fresh store is built
relative to the transaction it must share) is undecided and unused by any wave so far, whereas
composing `IdempotencyKeyRepository` directly onto this `UnitOfWork` gives the funding controllers
the same one-transaction guarantee (`find`, the deposit/withdrawal, and `save` all through
`self.session`, committed once) with no new lifecycle to invent.

`IdentityUnitOfWork`, `LedgerUnitOfWork`, and `OpsUnitOfWork` are each plain `UnitOfWork` subclasses
adding their own `cached_property` repositories (S0 §5's documented extension mechanism); combining
them via ordinary multiple inheritance -- rather than duplicating any of them -- is that same
mechanism composed, not a new one.
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
        """S3's `order`/`approval_hold` repos, added here (not a base-class change) so
        `OrderHoldsProvider` (`app/services/orders/holds_provider.py` -- "the real
        `CashPolicyService.HoldsProvider`... replaces `NullHoldsProvider` at its wiring point,
        `app/controllers/api/funding.py`") can finally be wired where its own docstring already
        says it belongs, without a new `UnitOfWork` class -- both repositories take any
        `UnitOfWork`, no `OrdersUnitOfWork`-specific mixin required."""
        return OrderRepository(self)

    @cached_property
    def approval_holds(self) -> ApprovalHoldRepository:
        return ApprovalHoldRepository(self)
