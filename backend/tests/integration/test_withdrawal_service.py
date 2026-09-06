"""`WithdrawalService` (S2 §5.3, FR-5/FR-41) — against real Postgres."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select, text

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
from app.services.identity.withdrawal_service import (
    BankReauthRequiredError,
    FundingNotEligibleError,
    WithdrawalService,
)
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


def _customer(
    db_committing,
    *,
    kyc_status: KycStatus = KycStatus.approved,
    account_approval_status: AccountApprovalStatus = AccountApprovalStatus.approved,
) -> uuid.UUID:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=kyc_status,
        account_approval_status=account_approval_status,
    )
    db_committing.add(customer)
    db_committing.flush()
    db_committing.add(Account.create(AccountRole.CASH, customer_id=customer.id))
    db_committing.add(Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer.id))
    db_committing.add(CustomerCashLock(customer_id=customer.id))
    db_committing.commit()
    return customer.id


def _link(db_committing, customer_id: uuid.UUID, *, status=BankLinkStatus.ACTIVE) -> BankLink:
    link = BankLink(
        customer_id=customer_id,
        plaid_item_id=f"item-{uuid.uuid4()}",
        plaid_access_token="access-token",
        status=status,
    )
    db_committing.add(link)
    db_committing.commit()
    return link


def _settled_deposit(db_committing, customer_id: uuid.UUID, *, amount: Money) -> None:
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        result = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        ).initiate(customer_id, amount=amount)
        uow.commit()
    with FundingUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP) as uow:
        obligation = uow.settlement_obligations.get_by_id(result.settlement_obligation_id)
        assert obligation is not None
        uow.settlement_obligations.confirm(obligation, confirmed_at=datetime.now(UTC))
        uow.commit()


def test_initiate_posts_a_balanced_withdrawal_entry_against_the_active_link(db_committing) -> None:
    customer_id = _customer(db_committing)
    link = _link(db_committing, customer_id)
    _settled_deposit(db_committing, customer_id, amount=Money("1000.00"))

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        result = WithdrawalService(uow, cash_policy=cash_policy).initiate(
            customer_id, amount=Money("400.00")
        )
        uow.commit()

    assert result.destination_bank_link_id == link.id
    postings = db_committing.execute(
        select(Posting).where(Posting.journal_entry_id == result.journal_entry_id)
    ).scalars().all()
    total = sum((p.amount_money for p in postings), Money("0.00"))
    assert total == Money("0.00")


def test_initiate_rejects_when_account_approval_is_still_pending(db_committing) -> None:
    customer_id = _customer(
        db_committing, account_approval_status=AccountApprovalStatus.pending
    )
    _link(db_committing, customer_id)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        with pytest.raises(
            FundingNotEligibleError, match="account_approval_status_pending"
        ):
            WithdrawalService(uow, cash_policy=cash_policy).initiate(
                customer_id, amount=Money("1.00")
            )


def test_initiate_rejects_when_bank_link_requires_reauth(db_committing) -> None:
    customer_id = _customer(db_committing)
    link = _link(db_committing, customer_id)
    _settled_deposit(db_committing, customer_id, amount=Money("1000.00"))
    link.status = BankLinkStatus.REQUIRES_REAUTH
    db_committing.commit()

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=NullHoldsProvider())
        with pytest.raises(BankReauthRequiredError):
            WithdrawalService(uow, cash_policy=cash_policy).initiate(
                customer_id, amount=Money("400.00")
            )
