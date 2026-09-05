"""`AccountApprovalService` (S2 §4, ADR 21) — the custodian-side account-approval lifecycle.

Distinct from `KycService`: it only ever writes `customer.account_approval_status`, never
`customer.kyc_status` (S2 §3.1/§4's conjunction -- the two gates are independent, not aliases of
one another). **Decided (ADR 21): Alpaca Paper Trading has no per-customer onboarding verdict to
wait on**, so this transition is simulated -- approval fires automatically the moment
`kyc_status = approved`, with a `simulated: true` marker on the log entry so the distinction from a
genuine third-party verdict is never lost.

Approval is also the natural moment this system first needs the customer's own ledger accounts to
exist: nothing before this point creates them (`register()`, Wave 2, only creates the `customer`
row), and `customer_cash_lock`'s own docstring says "every customer must have one" -- so
`approve_if_eligible` creates the `cash`/`customer_equity` accounts and the cash-lock row here,
idempotently, the same transaction as flipping the approval flag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from app.core.logging import get_logger
from app.models.identity.customer import AccountApprovalStatus, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock

if TYPE_CHECKING:
    import uuid

    from app.services.identity.funding_uow import FundingUnitOfWork

log = get_logger(__name__)


class AccountApprovalService:
    def __init__(self, uow: FundingUnitOfWork) -> None:
        self._uow = uow

    def approve_if_eligible(self, customer_id: uuid.UUID) -> bool:
        """Idempotent: a no-op unless `kyc_status = approved` and approval has not already been
        granted. Returns whether approval was granted by this call."""
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:
            raise ValueError(f"no customer found for id={customer_id!r}")
        if customer.kyc_status is not KycStatus.approved:
            return False
        if customer.account_approval_status is AccountApprovalStatus.approved:
            return False

        self._ensure_ledger_accounts(customer_id)
        customer.account_approval_status = AccountApprovalStatus.approved
        log.info("account_approval_granted", customer_id=str(customer_id), simulated=True)
        return True

    def _ensure_ledger_accounts(self, customer_id: uuid.UUID) -> None:
        for role in (AccountRole.CASH, AccountRole.CUSTOMER_EQUITY):
            existing = self._uow.session.execute(
                select(Account).where(Account.customer_id == customer_id, Account.role == role)
            ).scalar_one_or_none()
            if existing is None:
                self._uow.accounts.add(Account.create(role, customer_id=customer_id))

        existing_lock = self._uow.session.execute(
            select(CustomerCashLock).where(CustomerCashLock.customer_id == customer_id)
        ).scalar_one_or_none()
        if existing_lock is None:
            self._uow.cash_locks.create_for_customer(customer_id)
