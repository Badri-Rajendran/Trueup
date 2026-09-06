"""`WithdrawalService` (S2 §5.3, FR-5/FR-41)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.identity.bank_link import BankLink, BankLinkStatus
from app.models.identity.customer import AccountApprovalStatus, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.services.ledger.posting_service import PostingLeg, PostingService

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.core.money import Money
    from app.services.identity.funding_uow import FundingUnitOfWork
    from app.services.ledger.cash_policy_service import CashPolicyService


class FundingNotEligibleError(RuntimeError):
    """S2 §3.1's conjunction, checked on every withdrawal too -- not just deposits (per S2 §3.1:
    both services check both statuses every time, not once at account creation)."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"funding is not eligible: {reason}")
        self.reason = reason


class NoActiveBankLinkError(RuntimeError):
    """No `bank_link` row at all is linked for this customer yet (FR-4/FR-41)."""


class BankReauthRequiredError(RuntimeError):
    """FR-43: the active link is `requires_reauth`. Never silently retried against the stale
    Item."""


class InsufficientWithdrawableCashError(RuntimeError):
    """S2 §5.3/ADR 5: `amount` exceeds `withdrawable` -- checked even when it is within
    `investable` (S2 §7 edge case 4). Never relaxed to `investable`; ADR 5 calls swapping the two
    "a regulatory-grade bug, not a cosmetic one"."""


@dataclass(frozen=True, slots=True)
class WithdrawalResult:
    journal_entry_id: uuid.UUID
    destination_bank_link_id: uuid.UUID


class WithdrawalService:
    def __init__(
        self,
        uow: FundingUnitOfWork,
        *,
        cash_policy: CashPolicyService,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._cash_policy = cash_policy
        self._now = now

    def initiate(self, customer_id: uuid.UUID, *, amount: Money) -> WithdrawalResult:
        self._check_funding_eligibility(customer_id)
        destination = self._check_active_bank_link(customer_id)
        self._uow.cash_locks.acquire(customer_id)

        withdrawable = self._cash_policy.withdrawable(customer_id)
        if amount > withdrawable:
            raise InsufficientWithdrawableCashError(
                f"withdrawal of {amount} exceeds withdrawable {withdrawable} for customer "
                f"{customer_id!r}"
            )

        cash_account = self._account_for(customer_id, role=AccountRole.CASH)
        equity_account = self._account_for(customer_id, role=AccountRole.CUSTOMER_EQUITY)

        event = InboundEvent(
            source=InboundEventSource.PLAID,
            source_event_id=f"withdrawal_initiated:{uuid.uuid4()}",
            payload={"customer_id": str(customer_id), "amount": str(amount)},
            signature_verified=True,
        )
        self._uow.inbound_events.add(event)
        self._uow.session.flush()

        entry = PostingService(self._uow).post(
            entry_type=JournalEntryType.WITHDRAWAL,
            effective_date=self._now().astimezone(UTC).date(),
            source_event_id=event.id,
            legs=[
                PostingLeg(account_id=cash_account.id, amount_money=-amount),
                PostingLeg(account_id=equity_account.id, amount_money=amount),
            ],
        )

        return WithdrawalResult(journal_entry_id=entry.id, destination_bank_link_id=destination.id)

    def _check_funding_eligibility(self, customer_id: uuid.UUID) -> None:
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:
            raise FundingNotEligibleError("customer_not_found")
        if customer.kyc_status is not KycStatus.approved:
            raise FundingNotEligibleError(f"kyc_status_{customer.kyc_status.value}")
        if customer.account_approval_status is not AccountApprovalStatus.approved:
            raise FundingNotEligibleError(
                f"account_approval_status_{customer.account_approval_status.value}"
            )

    def _check_active_bank_link(self, customer_id: uuid.UUID) -> BankLink:
        link = self._uow.bank_links.current_for_customer(customer_id)
        if link is None:
            raise NoActiveBankLinkError(f"no active bank_link for customer {customer_id!r}")
        if link.status is BankLinkStatus.REQUIRES_REAUTH:
            raise BankReauthRequiredError(
                f"bank_link for customer {customer_id!r} requires re-authentication (FR-43)"
            )
        return link

    def _account_for(self, customer_id: uuid.UUID, *, role: AccountRole) -> Account:
        account = self._uow.session.execute(
            select(Account).where(Account.customer_id == customer_id, Account.role == role)
        ).scalar_one_or_none()
        if account is None:
            raise RuntimeError(
                f"customer {customer_id!r} has no {role.value} account -- account approval "
                "should have created it (S2's AccountApprovalService)"
            )
        return account
