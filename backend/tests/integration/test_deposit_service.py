"""`DepositService` (S2 §5.2, FR-5/FR-6) — against real Postgres, since it spans identity and
ledger tables in one transaction and depends on real RLS-scoped repository reads."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

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
from app.models.ledger.settlement_obligation import SettlementObligation, SettlementObligationStatus
from app.models.ops.inbound_event import InboundEvent
from app.services.identity.deposit_service import (
    BankReauthRequiredError,
    DepositCapExceededError,
    DepositService,
    FundingNotEligibleError,
)
from app.services.identity.funding_uow import FundingUnitOfWork

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


def _approved_customer(
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


def _active_link(db_committing, customer_id: uuid.UUID, *, status=BankLinkStatus.ACTIVE) -> None:
    db_committing.add(
        BankLink(
            customer_id=customer_id,
            plaid_item_id=f"item-{uuid.uuid4()}",
            plaid_access_token="access-token",
            status=status,
        )
    )
    db_committing.commit()


def test_initiate_posts_a_balanced_deposit_entry_and_a_pending_obligation(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: datetime(2026, 9, 5, 12, 0, tzinfo=UTC),
        )
        result = service.initiate(customer_id, amount=Money("500.00"))
        uow.commit()

    postings = db_committing.execute(
        select(Posting).where(Posting.journal_entry_id == result.journal_entry_id)
    ).scalars().all()
    total = sum((p.amount_money for p in postings), Money("0.00"))
    assert total == Money("0.00")
    assert len(postings) == 2

    obligation = db_committing.execute(
        select(SettlementObligation).where(
            SettlementObligation.id == result.settlement_obligation_id
        )
    ).scalar_one()
    assert obligation.status is SettlementObligationStatus.PENDING
    assert result.expected_settlement_date == date(2026, 9, 7)


def test_initiate_rejects_when_kyc_is_not_approved(db_committing) -> None:
    customer_id = _approved_customer(db_committing, kyc_status=KycStatus.pending)
    _active_link(db_committing, customer_id)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        )
        with pytest.raises(FundingNotEligibleError, match="kyc_status_pending"):
            service.initiate(customer_id, amount=Money("500.00"))


def test_initiate_rejects_when_bank_link_requires_reauth(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id, status=BankLinkStatus.REQUIRES_REAUTH)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        )
        with pytest.raises(BankReauthRequiredError):
            service.initiate(customer_id, amount=Money("500.00"))


def test_initiate_rejects_over_the_per_transaction_cap(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        )
        with pytest.raises(DepositCapExceededError):
            service.initiate(customer_id, amount=Money("25000.01"))


def test_initiate_rejects_a_second_deposit_that_would_exceed_the_daily_cap(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    clock = lambda: datetime(2026, 9, 5, 12, 0, tzinfo=UTC)  # noqa: E731

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=clock,
        )
        service.initiate(customer_id, amount=Money("25000.00"))
        uow.commit()

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=clock,
        )
        service.initiate(customer_id, amount=Money("25000.00"))
        uow.commit()

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=clock,
        )
        with pytest.raises(DepositCapExceededError, match="per_day"):
            service.initiate(customer_id, amount=Money("0.01"))


def test_apply_ach_return_fails_the_obligation_and_posts_a_correction_entry(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    clock = lambda: datetime(2026, 9, 5, 12, 0, tzinfo=UTC)  # noqa: E731

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=clock,
        )
        result = service.initiate(customer_id, amount=Money("500.00"))
        uow.commit()

    with FundingUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=clock,
        )
        service.apply_ach_return(result.settlement_obligation_id)
        uow.commit()

    obligation = db_committing.execute(
        select(SettlementObligation).where(
            SettlementObligation.id == result.settlement_obligation_id
        )
    ).scalar_one()
    assert obligation.status is SettlementObligationStatus.FAILED

    receivable_account = db_committing.execute(
        select(Account).where(
            Account.customer_id == customer_id, Account.role == AccountRole.CUSTOMER_RECEIVABLE
        )
    ).scalar_one()
    receivable_posting = db_committing.execute(
        select(Posting).where(Posting.account_id == receivable_account.id)
    ).scalar_one()
    assert receivable_posting.amount_money == Money("500.00")
