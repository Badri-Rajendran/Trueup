"""S2 §7 edge case 1 -- a concurrent deposit and withdrawal for the same customer are serialized by
`customer_cash_lock` (S1 §3.5), never allowed to interleave their check-then-write."""

from __future__ import annotations

import base64
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from app.config import Settings
from app.core.crypto import reset_cipher, set_cipher
from app.core.money import Money
from app.core.uow import SessionRole
from app.extensions import DbRole, dispose_engines, init_engines
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.models.identity.bank_link import BankLink, BankLinkStatus
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.inbound_event import InboundEvent
from app.services.identity.deposit_service import DepositService
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.identity.null_holds_provider import NullHoldsProvider
from app.services.identity.withdrawal_service import WithdrawalService
from app.services.ledger.cash_policy_service import CashPolicyService

_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    BankLink.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
]

pytestmark = pytest.mark.usefixtures("_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    set_cipher(LocalDevCipher(base64.b64encode(b"0" * 32).decode()))
    yield None
    dispose_engines()
    reset_cipher()


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _funded_customer(db_committing) -> uuid.UUID:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=KycStatus.approved,
        account_approval_status=AccountApprovalStatus.approved,
    )
    db_committing.add(customer)
    db_committing.flush()
    db_committing.add(Account.create(AccountRole.CASH, customer_id=customer.id))
    db_committing.add(Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer.id))
    db_committing.add(CustomerCashLock(customer_id=customer.id))
    db_committing.add(
        BankLink(
            customer_id=customer.id,
            plaid_item_id=f"item-{uuid.uuid4()}",
            plaid_access_token="access-token",
            status=BankLinkStatus.ACTIVE,
        )
    )
    db_committing.commit()
    return customer.id


def test_concurrent_deposit_and_withdrawal_never_interleave_their_check_and_write(
    db_committing,
) -> None:
    customer_id = _funded_customer(db_committing)

    # Settled cash so `withdrawable` counts it.
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        result = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        ).initiate(customer_id, amount=Money("1000.00"))
        uow.commit()

    with FundingUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow:
        obligation = uow.settlement_obligations.get_by_id(result.settlement_obligation_id)
        assert obligation is not None
        uow.settlement_obligations.confirm(obligation, confirmed_at=datetime.now(UTC))
        uow.commit()

    # Assert on the withdrawal thread's own block duration, not commit-order list-append
    # (a genuine cross-connection race, not a Python thread-scheduling one).
    hold_seconds = 0.4
    deposit_acquired = threading.Event()
    withdrawal_blocked_for: list[float] = []

    def hold_the_lock_during_a_deposit() -> None:
        with FundingUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        ) as uow:
            uow.cash_locks.acquire(customer_id)
            deposit_acquired.set()
            time.sleep(hold_seconds)
            uow.commit()

    def attempt_a_withdrawal() -> None:
        with FundingUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        ) as uow:
            started_at = time.monotonic()
            uow.cash_locks.acquire(customer_id)
            withdrawal_blocked_for.append(time.monotonic() - started_at)
            uow.commit()

    deposit_thread = threading.Thread(target=hold_the_lock_during_a_deposit)
    deposit_thread.start()
    assert deposit_acquired.wait(timeout=5), "deposit thread never acquired the cash lock"

    withdrawal_thread = threading.Thread(target=attempt_a_withdrawal)
    withdrawal_thread.start()
    deposit_thread.join(timeout=5)
    withdrawal_thread.join(timeout=5)

    assert len(withdrawal_blocked_for) == 1, "withdrawal thread never completed"
    # Tolerance below the full hold; near-instant would mean interleaving, not blocking.
    assert withdrawal_blocked_for[0] >= hold_seconds * 0.75


def test_withdrawal_counts_only_settled_cash_never_unsettled_deposit_proceeds(
    db_committing,
) -> None:
    """S2 §7 edge case 4: unsettled deposit inflates `investable` above `withdrawable` (ADR 5)."""
    customer_id = _funded_customer(db_committing)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        ).initiate(customer_id, amount=Money("1000.00"))
        uow.commit()
    # Left unconfirmed: settled_cash is 0, investable is 1000.

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        assert cash_policy.withdrawable(customer_id) == Money("0.00")
        assert cash_policy.investable(customer_id) == Money("1000.00")

        service = WithdrawalService(uow, cash_policy=cash_policy)
        from app.services.identity.withdrawal_service import InsufficientWithdrawableCashError

        with pytest.raises(InsufficientWithdrawableCashError):
            service.initiate(customer_id, amount=Money("500.00"))
