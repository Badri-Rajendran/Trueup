"""`DepositService` (S2 §5.2, FR-5/FR-6)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.models.identity.bank_link import BankLinkStatus
from app.models.identity.customer import AccountApprovalStatus, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.services.identity._shared import deposited_on
from app.services.ledger.posting_service import PostingLeg, PostingService

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from app.core.money import Money
    from app.services.identity.funding_uow import FundingUnitOfWork

_ACH_SETTLEMENT_CALENDAR_DAYS = 2
"""Stand-in for Plaid's ACH timeline (S2 §5.2 step 3); flagged for compliance review before go-live."""


class FundingNotEligibleError(RuntimeError):
    """S2 §3.1: `kyc_status` and `account_approval_status` must both be `approved`."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"funding is not eligible: {reason}")
        self.reason = reason


class NoActiveBankLinkError(RuntimeError):
    """No `bank_link` row at all is linked for this customer yet (FR-4)."""


class BankReauthRequiredError(RuntimeError):
    """FR-43: the active link is `requires_reauth`; the customer must re-link (S2 §5.4)."""


class DepositCapExceededError(RuntimeError):
    """`cap` is `"per_transaction"` or `"per_day"` (S2 §5.2 step 2)."""

    def __init__(self, cap: str) -> None:
        super().__init__(f"deposit exceeds the {cap} cap")
        self.cap = cap


class SettlementObligationNotFoundError(RuntimeError):
    """Raised when an ACH-return webhook names an unknown `settlement_obligation`."""


@dataclass(frozen=True, slots=True)
class DepositResult:
    journal_entry_id: uuid.UUID
    settlement_obligation_id: uuid.UUID
    expected_settlement_date: date


def check_deposit_caps(
    amount: Money, *, deposited_today: Money, cap_per_transaction: Money, cap_per_day: Money
) -> None:
    """S2 §5.2 step 2's two caps, as pure logic."""
    if amount > cap_per_transaction:
        raise DepositCapExceededError("per_transaction")
    if deposited_today + amount > cap_per_day:
        raise DepositCapExceededError("per_day")


def build_ach_return_correction_legs(
    *, cash_account_id: uuid.UUID, receivable_account_id: uuid.UUID, amount: Money
) -> list[PostingLeg]:
    """S2 §5.2 step 4's correction entry: moves `amount` from `cash` to `customer_receivable`."""
    return [
        PostingLeg(account_id=cash_account_id, amount_money=-amount),
        PostingLeg(account_id=receivable_account_id, amount_money=amount),
    ]


class DepositService:
    def __init__(
        self,
        uow: FundingUnitOfWork,
        *,
        deposit_cap_per_transaction: Money,
        deposit_cap_per_day: Money,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._cap_per_transaction = deposit_cap_per_transaction
        self._cap_per_day = deposit_cap_per_day
        self._now = now

    def initiate(self, customer_id: uuid.UUID, *, amount: Money) -> DepositResult:
        self._check_funding_eligibility(customer_id)
        self._check_active_bank_link(customer_id)
        self._uow.cash_locks.acquire(customer_id)

        today = self._now().astimezone(UTC).date()
        deposited_today = self._deposited_today(customer_id, today=today)
        check_deposit_caps(
            amount,
            deposited_today=deposited_today,
            cap_per_transaction=self._cap_per_transaction,
            cap_per_day=self._cap_per_day,
        )

        cash_account = self._account_for(customer_id, role=AccountRole.CASH)
        equity_account = self._account_for(customer_id, role=AccountRole.CUSTOMER_EQUITY)

        entry_event = self._record_inbound_event(
            customer_id, amount=amount, kind="deposit_initiated"
        )
        entry = PostingService(self._uow).post(
            entry_type=JournalEntryType.DEPOSIT,
            effective_date=today,
            source_event_id=entry_event.id,
            legs=[
                PostingLeg(account_id=cash_account.id, amount_money=amount),
                PostingLeg(account_id=equity_account.id, amount_money=-amount),
            ],
        )

        obligation_event = self._record_inbound_event(
            customer_id, amount=amount, kind="deposit_settlement_expected"
        )
        expected_settlement_date = today + timedelta(days=_ACH_SETTLEMENT_CALENDAR_DAYS)
        obligation = SettlementObligation(
            journal_entry_id=entry.id,
            account_id=cash_account.id,
            amount_money=amount,
            expected_settlement_date=expected_settlement_date,
            source_event_id=obligation_event.id,
        )
        self._uow.settlement_obligations.add(obligation)
        self._uow.session.flush()

        return DepositResult(
            journal_entry_id=entry.id,
            settlement_obligation_id=obligation.id,
            expected_settlement_date=expected_settlement_date,
        )

    def apply_ach_return(self, settlement_obligation_id: uuid.UUID) -> None:
        """FR-6: ACH debit bounced. Fails the obligation and posts a correction entry (S2 §5.2 step 4)."""
        obligation = self._uow.settlement_obligations.get_by_id(settlement_obligation_id)
        if obligation is None:
            raise SettlementObligationNotFoundError(
                f"no settlement_obligation found for id={settlement_obligation_id!r}"
            )
        cash_account = self._uow.accounts.get_by_id(obligation.account_id)
        if cash_account is None or cash_account.customer_id is None:
            raise SettlementObligationNotFoundError(
                f"settlement_obligation {settlement_obligation_id!r} has no owning cash account"
            )
        customer_id = cash_account.customer_id

        self._uow.settlement_obligations.fail(
            obligation, failed_at=self._now(), reason="ach_return"
        )

        receivable_account = self._account_for(customer_id, role=AccountRole.CUSTOMER_RECEIVABLE)
        correction_event = self._record_inbound_event(
            customer_id, amount=obligation.amount_money, kind="deposit_ach_return"
        )
        PostingService(self._uow).post(
            entry_type=JournalEntryType.CORRECTION,
            effective_date=self._now().astimezone(UTC).date(),
            source_event_id=correction_event.id,
            legs=build_ach_return_correction_legs(
                cash_account_id=cash_account.id,
                receivable_account_id=receivable_account.id,
                amount=obligation.amount_money,
            ),
            memo="ACH return on bounced deposit (S2 §5.2 step 4)",
        )

    # --- internals --------------------------------------------------------------------------

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

    def _check_active_bank_link(self, customer_id: uuid.UUID) -> None:
        link = self._uow.bank_links.current_for_customer(customer_id)
        if link is None:
            raise NoActiveBankLinkError(f"no active bank_link for customer {customer_id!r}")
        if link.status is BankLinkStatus.REQUIRES_REAUTH:
            raise BankReauthRequiredError(
                f"bank_link for customer {customer_id!r} requires re-authentication (FR-43)"
            )

    def _deposited_today(self, customer_id: uuid.UUID, *, today: date) -> Money:
        return deposited_on(self._uow, customer_id, effective_date=today)

    def _account_for(self, customer_id: uuid.UUID, *, role: AccountRole) -> Account:
        account = self._uow.session.execute(
            select(Account).where(Account.customer_id == customer_id, Account.role == role)
        ).scalar_one_or_none()
        if account is None:
            if role is AccountRole.CUSTOMER_RECEIVABLE:
                account = Account.create(role, customer_id=customer_id)
                self._uow.accounts.add(account)
                self._uow.session.flush()
                return account
            raise RuntimeError(
                f"customer {customer_id!r} has no {role.value} account -- account approval "
                "should have created it (S2's AccountApprovalService)"
            )
        return account

    def _record_inbound_event(
        self, customer_id: uuid.UUID, *, amount: Money, kind: str
    ) -> InboundEvent:
        event = InboundEvent(
            source=InboundEventSource.PLAID,
            source_event_id=f"{kind}:{uuid.uuid4()}",
            payload={"kind": kind, "customer_id": str(customer_id), "amount": str(amount)},
            signature_verified=True,
        )
        self._uow.inbound_events.add(event)
        self._uow.session.flush()
        return event
