"""`FundingSummaryService` (S2 §5.2/§6, FR-6) — against real Postgres, since it composes
`CashPolicyService` and a receivable-balance aggregate that both depend on RLS-scoped reads."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

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
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.services.identity.deposit_service import DepositService
from app.services.identity.funding_summary_service import FundingSummaryService
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.holds_provider import OrderHoldsProvider

_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    BankLink.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    Order.__table__,
    ApprovalHold.__table__,
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


def _approved_customer(db_committing) -> uuid.UUID:
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
    db_committing.commit()
    return customer.id


def _active_link(db_committing, customer_id: uuid.UUID) -> None:
    db_committing.add(
        BankLink(
            customer_id=customer_id,
            plaid_item_id=f"item-{uuid.uuid4()}",
            plaid_access_token="access-token",
            status=BankLinkStatus.ACTIVE,
        )
    )
    db_committing.commit()


def _summarize(customer_id: uuid.UUID, *, now: datetime):
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
        return FundingSummaryService(
            uow,
            cash_policy=cash_policy,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        ).summarize(customer_id)


def test_outstanding_receivable_is_zero_with_no_receivable_account_row(db_committing) -> None:
    customer_id = _approved_customer(db_committing)

    summary = _summarize(customer_id, now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC))

    assert summary.outstanding_receivable == Money("0.00")


def test_outstanding_receivable_reflects_an_ach_return(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        )
        result = service.initiate(customer_id, amount=Money("500.00"))
        service.apply_ach_return(result.settlement_obligation_id)
        uow.commit()

    summary = _summarize(customer_id, now=now)

    assert summary.outstanding_receivable == Money("500.00")


def test_deposited_today_excludes_prior_days_deposits(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    yesterday = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    today = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: yesterday,
        ).initiate(customer_id, amount=Money("300.00"))
        uow.commit()

    summary = _summarize(customer_id, now=today)

    assert summary.deposited_today == Money("0.00")


def test_deposited_today_excludes_non_deposit_postings(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        service = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        )
        result = service.initiate(customer_id, amount=Money("300.00"))
        service.apply_ach_return(result.settlement_obligation_id)
        uow.commit()

    summary = _summarize(customer_id, now=now)

    assert summary.deposited_today == Money("300.00")


def test_caps_are_reported_unchanged_from_the_constructor_arguments(db_committing) -> None:
    customer_id = _approved_customer(db_committing)

    summary = _summarize(customer_id, now=datetime(2026, 9, 5, 12, 0, tzinfo=UTC))

    assert summary.deposit_cap_per_transaction == Money("25000.00")
    assert summary.deposit_cap_per_day == Money("50000.00")


def test_withdrawable_and_investable_are_delegated_to_cash_policy(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        ).initiate(customer_id, amount=Money("500.00"))
        uow.commit()

    summary = _summarize(customer_id, now=now)

    # ADR 5: a same-day, unconfirmed deposit is investable but never withdrawable.
    assert summary.investable == Money("500.00")
    assert summary.withdrawable == Money("0.00")
    assert date(2026, 9, 5) == now.date()
