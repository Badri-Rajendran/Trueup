"""`FundingHistoryService` (S2 §6) — against real Postgres: the `Account.role == CASH` join
guard and the signed-amount convention both depend on real posting/account rows."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.config import Settings
from app.core.crypto import reset_cipher, set_cipher
from app.core.money import Money
from app.core.pagination import decode_cursor, paginate
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
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.services.identity.deposit_service import DepositService
from app.services.identity.funding_history_service import FundingHistoryEntry, FundingHistoryService
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


# --- pagination (S12 §8) ------------------------------------------------------------------------


def _seed_funding_entry(
    db_committing,
    *,
    cash_account_id: uuid.UUID,
    equity_account_id: uuid.UUID,
    effective_date: date,
    recorded_at: datetime,
    amount: Money,
    entry_id: uuid.UUID | None = None,
) -> JournalEntry:
    """A deposit's two legs, built directly rather than through `DepositService` so the caller can
    pin `effective_date`/`recorded_at`/`id` precisely (pagination-stability needs exact ties)."""
    event_row = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    db_committing.add(event_row)
    db_committing.flush()

    entry = JournalEntry(
        id=entry_id if entry_id is not None else uuid.uuid4(),
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=effective_date,
        recorded_at=recorded_at,
        source_event_id=event_row.id,
    )
    db_committing.add(entry)
    db_committing.flush()
    db_committing.add_all(
        [
            Posting(journal_entry_id=entry.id, account_id=cash_account_id, amount_money=amount),
            Posting(
                journal_entry_id=entry.id, account_id=equity_account_id, amount_money=-amount
            ),
        ]
    )
    db_committing.commit()
    return entry


def _cursor_key(entry: FundingHistoryEntry) -> tuple[str, str, str]:
    return (
        entry.effective_date.isoformat(),
        entry.recorded_at.isoformat(),
        str(entry.journal_entry_id),
    )


def _decode_after(raw_cursor: str) -> tuple[date, datetime, uuid.UUID]:
    decoded = decode_cursor(raw_cursor)
    return (
        date.fromisoformat(decoded[0]),  # type: ignore[arg-type]
        datetime.fromisoformat(decoded[1]),  # type: ignore[arg-type]
        uuid.UUID(decoded[2]),  # type: ignore[arg-type]
    )


def test_history_pagination_is_stable_under_a_mid_walk_insert(db_committing) -> None:
    customer_id = _approved_customer(db_committing)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    db_committing.add_all([cash, equity])
    db_committing.commit()

    base_date = date(2026, 9, 1)
    base_recorded = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    seeded = [
        _seed_funding_entry(
            db_committing,
            cash_account_id=cash.id,
            equity_account_id=equity.id,
            effective_date=base_date + timedelta(days=i),
            recorded_at=base_recorded + timedelta(days=i),
            amount=Money(f"{100 * (i + 1)}.00"),
        )
        for i in range(5)
    ]
    # DESC order: seeded[4] (latest dates) is newest ... seeded[0] is oldest.
    newest_first = list(reversed(seeded))

    def _uow() -> FundingUnitOfWork:
        return FundingUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        )

    with _uow() as uow:
        rows = FundingHistoryService(uow).history(customer_id, as_of=Watermark.live(), limit=2)
        page1 = paginate(rows, limit=2, cursor_key=_cursor_key)
    assert [e.journal_entry_id for e in page1.items] == [newest_first[0].id, newest_first[1].id]
    assert page1.next_cursor is not None

    # An entry tied on both `effective_date` and `recorded_at` with newest_first[1], given a
    # deliberately-maximal `id` (guaranteed greater than any uuid4) so the DESC tiebreak places it
    # strictly before newest_first[1] -- into page 1's already-yielded position -- after page 1
    # has already been fetched.
    mid_insert = _seed_funding_entry(
        db_committing,
        cash_account_id=cash.id,
        equity_account_id=equity.id,
        effective_date=newest_first[1].effective_date,
        recorded_at=newest_first[1].recorded_at,
        amount=Money("999.00"),
        entry_id=uuid.UUID(int=2**128 - 1),
    )

    after = _decode_after(page1.next_cursor)
    with _uow() as uow:
        rows = FundingHistoryService(uow).history(
            customer_id, as_of=Watermark.live(), limit=2, after=after
        )
        page2 = paginate(rows, limit=2, cursor_key=_cursor_key)
    assert [e.journal_entry_id for e in page2.items] == [newest_first[2].id, newest_first[3].id]
    assert page2.next_cursor is not None

    after = _decode_after(page2.next_cursor)
    with _uow() as uow:
        rows = FundingHistoryService(uow).history(
            customer_id, as_of=Watermark.live(), limit=2, after=after
        )
        page3 = paginate(rows, limit=2, cursor_key=_cursor_key)
    assert [e.journal_entry_id for e in page3.items] == [newest_first[4].id]
    assert page3.next_cursor is None

    walked_ids = [e.journal_entry_id for page in (page1, page2, page3) for e in page.items]
    assert walked_ids == [e.id for e in newest_first]  # every seeded row exactly once, in order
    assert mid_insert.id not in walked_ids  # the mid-walk insert never leaks into the walk
