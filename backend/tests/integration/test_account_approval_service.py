"""`AccountApprovalService` (S2 §4, ADR 21) -- against real Postgres, since it writes both
`customer` and S1's ledger tables in one transaction."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select, text

from app.config import Settings
from app.core.uow import SessionRole
from app.extensions import DbRole, dispose_engines, init_engines
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.services.identity.account_approval_service import AccountApprovalService
from app.services.identity.funding_uow import FundingUnitOfWork

pytestmark = pytest.mark.usefixtures("_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    tables = [Customer.__table__, Account.__table__, CustomerCashLock.__table__]
    for table in tables:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    # DROP ... CASCADE, not `.drop()`: another file's session-scoped fixture (e.g. test_orders.py's
    # `order`/`approval_hold`) may hold a live FK into `customer` at teardown time -- a real,
    # previously-documented cascade (5 known teardown-only errors, DECISION-LOG.md). CASCADE
    # removes just that dependent constraint, matching test_fee_charge_schema.py's own fix.
    with owner_engine.begin() as connection:
        for table in reversed(tables):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _insert_customer(db_committing, *, kyc_status: KycStatus) -> uuid.UUID:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=kyc_status,
        account_approval_status=AccountApprovalStatus.pending,
    )
    db_committing.add(customer)
    db_committing.commit()
    return customer.id


def test_approval_is_a_no_op_while_kyc_is_still_pending(db_committing) -> None:
    customer_id = _insert_customer(db_committing, kyc_status=KycStatus.pending)

    with FundingUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER
    ) as uow:
        service = AccountApprovalService(uow)
        applied = service.approve_if_eligible(customer_id)
        uow.commit()

    assert applied is False
    customer = db_committing.execute(
        select(Customer).where(Customer.id == customer_id)
    ).scalar_one()
    assert customer.account_approval_status is AccountApprovalStatus.pending


def test_approval_creates_ledger_accounts_and_cash_lock_once_kyc_is_approved(
    db_committing,
) -> None:
    customer_id = _insert_customer(db_committing, kyc_status=KycStatus.approved)

    with FundingUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER
    ) as uow:
        service = AccountApprovalService(uow)
        applied = service.approve_if_eligible(customer_id)
        uow.commit()

    assert applied is True
    customer = db_committing.execute(
        select(Customer).where(Customer.id == customer_id)
    ).scalar_one()
    assert customer.account_approval_status is AccountApprovalStatus.approved

    accounts = db_committing.execute(
        select(Account).where(Account.customer_id == customer_id)
    ).scalars().all()
    roles = {account.role for account in accounts}
    assert roles == {AccountRole.CASH, AccountRole.CUSTOMER_EQUITY}

    lock = db_committing.execute(
        select(CustomerCashLock).where(CustomerCashLock.customer_id == customer_id)
    ).scalar_one_or_none()
    assert lock is not None


def test_approval_is_idempotent_and_never_duplicates_accounts(db_committing) -> None:
    customer_id = _insert_customer(db_committing, kyc_status=KycStatus.approved)

    for _ in range(2):
        with FundingUnitOfWork(
            customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER
        ) as uow:
            AccountApprovalService(uow).approve_if_eligible(customer_id)
            uow.commit()

    accounts = db_committing.execute(
        select(Account).where(Account.customer_id == customer_id)
    ).scalars().all()
    assert len(accounts) == 2
