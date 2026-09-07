"""`FundingHistoryService` (S2 §6) — against real Postgres: the `Account.role == CASH` join
guard and the signed-amount convention both depend on real posting/account rows."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from app.config import Settings
from app.core.crypto import reset_cipher, set_cipher
from app.core.money import Money
from app.core.uow import SessionRole
from app.core.watermark import Watermark
from app.extensions import DbRole, dispose_engines, init_engines
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.models.identity.bank_link import BankLink, BankLinkStatus
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import (
    SettlementObligation,
    SettlementObligationStatus,
)
from app.models.ops.inbound_event import InboundEvent
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.services.identity.deposit_service import DepositService
from app.services.identity.funding_history_service import FundingHistoryService
from app.services.identity.funding_uow import FundingUnitOfWork
from app.services.identity.withdrawal_service import WithdrawalService
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


def _deposit(customer_id: uuid.UUID, *, amount: Money, now: datetime):
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        result = DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        ).initiate(customer_id, amount=amount)
        uow.commit()
        return result


def _history(customer_id: uuid.UUID):
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        return FundingHistoryService(uow).history(customer_id, as_of=Watermark.live())


def test_history_reports_signed_cash_leg_amounts_only(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    _deposit(customer_id, amount=Money("500.00"), now=now)

    entries = _history(customer_id)

    assert len(entries) == 1
    assert entries[0].amount == Money("500.00")


def test_history_excludes_the_correction_entry_for_a_returned_deposit(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    result = _deposit(customer_id, amount=Money("500.00"), now=now)
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
            now=lambda: now,
        ).apply_ach_return(result.settlement_obligation_id)
        uow.commit()

    entries = _history(customer_id)

    assert len(entries) == 1
    assert entries[0].settlement_status == SettlementObligationStatus.FAILED
    assert entries[0].amount == Money("500.00")


def test_each_deposit_maps_its_own_obligation_not_a_shared_or_stale_one(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    first = _deposit(customer_id, amount=Money("100.00"), now=now)
    second = _deposit(customer_id, amount=Money("200.00"), now=now)
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        obligation = uow.settlement_obligations.get_by_id(first.settlement_obligation_id)
        assert obligation is not None
        uow.settlement_obligations.confirm(obligation, confirmed_at=now)
        uow.commit()

    entries = {e.journal_entry_id: e for e in _history(customer_id)}

    assert entries[first.journal_entry_id].settlement_status == SettlementObligationStatus.CONFIRMED
    assert entries[second.journal_entry_id].settlement_status == SettlementObligationStatus.PENDING


def test_history_orders_newest_first_by_effective_then_recorded_date(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    earlier = datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    later = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    first = _deposit(customer_id, amount=Money("100.00"), now=earlier)
    second = _deposit(customer_id, amount=Money("200.00"), now=later)

    entries = _history(customer_id)

    assert [e.journal_entry_id for e in entries] == [
        second.journal_entry_id,
        first.journal_entry_id,
    ]


def test_history_respects_the_watermark_cutoff(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    _deposit(customer_id, amount=Money("500.00"), now=now)

    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        entries = FundingHistoryService(uow).history(
            customer_id, as_of=Watermark.as_published(datetime(2020, 1, 1, tzinfo=UTC))
        )

    assert entries == []


def test_history_includes_a_withdrawal_with_a_negative_amount(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    _active_link(db_committing, customer_id)
    now = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)

    result = _deposit(customer_id, amount=Money("500.00"), now=now)
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        obligation = uow.settlement_obligations.get_by_id(result.settlement_obligation_id)
        assert obligation is not None
        uow.settlement_obligations.confirm(obligation, confirmed_at=now)
        uow.commit()
    with FundingUnitOfWork(
        customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
    ) as uow:
        cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
        WithdrawalService(uow, cash_policy=cash_policy, now=lambda: now).initiate(
            customer_id, amount=Money("100.00")
        )
        uow.commit()

    entries = {e.entry_type: e for e in _history(customer_id)}

    withdrawal = entries[JournalEntryType.WITHDRAWAL]
    assert withdrawal.amount == Money("-100.00")
    assert withdrawal.settlement_status is None
