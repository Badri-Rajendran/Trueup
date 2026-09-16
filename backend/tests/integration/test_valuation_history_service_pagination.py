"""`HistoryService.history` (S4 §7, S12 §8) — keyset-pagination stability against real Postgres:
paging with `limit=4` across 5 seeded deposits (10 posting-leg rows) survives a new deposit
inserted mid-walk into an already-yielded page's position, with no repeated or skipped row.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import Engine, text

from app.core.db import DbRole
from app.core.money import Money
from app.core.pagination import decode_cursor, paginate
from app.core.uow import SessionRole
from app.core.watermark import Watermark
from app.models.identity.customer import Customer
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.services.valuation.history_service import HistoryEntry, HistoryService
from app.services.valuation.uow import ValuationUnitOfWork
from tests.integration.conftest import insert_customer

_TABLES = [
    Customer.__table__,
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
]


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("_tables")


def _seed_deposit(
    db_committing,
    *,
    cash_account_id: uuid.UUID,
    equity_account_id: uuid.UUID,
    effective_date: date,
    recorded_at: datetime,
    amount: Money,
    cash_posting_id: uuid.UUID | None = None,
    equity_posting_id: uuid.UUID | None = None,
) -> JournalEntry:
    event_row = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    db_committing.add(event_row)
    db_committing.flush()

    entry = JournalEntry(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=effective_date,
        recorded_at=recorded_at,
        source_event_id=event_row.id,
    )
    db_committing.add(entry)
    db_committing.flush()
    db_committing.add_all(
        [
            Posting(
                id=cash_posting_id if cash_posting_id is not None else uuid.uuid4(),
                journal_entry_id=entry.id,
                account_id=cash_account_id,
                amount_money=amount,
            ),
            Posting(
                id=equity_posting_id if equity_posting_id is not None else uuid.uuid4(),
                journal_entry_id=entry.id,
                account_id=equity_account_id,
                amount_money=-amount,
            ),
        ]
    )
    db_committing.commit()
    return entry


def _cursor_key(entry: HistoryEntry) -> tuple[str, str, str]:
    return (entry.effective_date.isoformat(), entry.recorded_at.isoformat(), str(entry.posting_id))


def _decode_after(raw_cursor: str) -> tuple[date, datetime, uuid.UUID]:
    decoded = decode_cursor(raw_cursor)
    return (
        date.fromisoformat(decoded[0]),  # type: ignore[arg-type]
        datetime.fromisoformat(decoded[1]),  # type: ignore[arg-type]
        uuid.UUID(decoded[2]),  # type: ignore[arg-type]
    )


def test_history_pagination_is_stable_under_a_mid_walk_insert(db_committing) -> None:
    customer_id = insert_customer(db_committing)
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    db_committing.add_all([cash, equity])
    db_committing.commit()

    base_date = date(2026, 9, 1)
    base_recorded = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    # Deterministic intra-date tiebreak: within group i, the cash leg's id always exceeds the
    # equity leg's, so DESC order within one date is always [cash, equity].
    for i in range(5):
        _seed_deposit(
            db_committing,
            cash_account_id=cash.id,
            equity_account_id=equity.id,
            effective_date=base_date + timedelta(days=i),
            recorded_at=base_recorded + timedelta(days=i),
            amount=Money(f"{100 * (i + 1)}.00"),
            cash_posting_id=uuid.UUID(int=2 * i + 2),
            equity_posting_id=uuid.UUID(int=2 * i + 1),
        )
    # DESC walk (newest date first, cash leg before equity leg within a date):
    # [cash_4, equity_4, cash_3, equity_3, cash_2, equity_2, cash_1, equity_1, cash_0, equity_0]
    expected_walk = [
        uuid.UUID(int=n) for i in reversed(range(5)) for n in (2 * i + 2, 2 * i + 1)
    ]

    def _uow() -> ValuationUnitOfWork:
        return ValuationUnitOfWork(
            customer_id=customer_id, role=SessionRole.CUSTOMER, db_role=DbRole.APP
        )

    with _uow() as uow:
        rows = HistoryService(uow).history(customer_id, as_of=Watermark.live(), limit=4)
        page1 = paginate(rows, limit=4, cursor_key=_cursor_key)
    assert [e.posting_id for e in page1.items] == expected_walk[:4]
    assert page1.next_cursor is not None

    # A deposit tied on both dates with group i=3 (page 1's last-yielded date), given
    # deliberately-maximal posting ids (guaranteed greater than any uuid4 used above) so the DESC
    # tiebreak places both its legs strictly before group 3's own legs -- into page 1's
    # already-yielded position -- after page 1 has already been fetched.
    mid_insert_cash_id = uuid.UUID(int=2**128 - 1)
    mid_insert_equity_id = uuid.UUID(int=2**128 - 2)
    _seed_deposit(
        db_committing,
        cash_account_id=cash.id,
        equity_account_id=equity.id,
        effective_date=base_date + timedelta(days=3),
        recorded_at=base_recorded + timedelta(days=3),
        amount=Money("999.00"),
        cash_posting_id=mid_insert_cash_id,
        equity_posting_id=mid_insert_equity_id,
    )
    mid_insert_posting_ids = {mid_insert_cash_id, mid_insert_equity_id}

    after = _decode_after(page1.next_cursor)
    with _uow() as uow:
        rows = HistoryService(uow).history(
            customer_id, as_of=Watermark.live(), limit=4, after=after
        )
        page2 = paginate(rows, limit=4, cursor_key=_cursor_key)
    assert [e.posting_id for e in page2.items] == expected_walk[4:8]
    assert page2.next_cursor is not None

    after = _decode_after(page2.next_cursor)
    with _uow() as uow:
        rows = HistoryService(uow).history(
            customer_id, as_of=Watermark.live(), limit=4, after=after
        )
        page3 = paginate(rows, limit=4, cursor_key=_cursor_key)
    assert [e.posting_id for e in page3.items] == expected_walk[8:]
    assert page3.next_cursor is None

    walked_ids = [e.posting_id for page in (page1, page2, page3) for e in page.items]
    assert walked_ids == expected_walk  # every seeded posting exactly once, in order
    assert not (mid_insert_posting_ids & set(walked_ids))  # mid-walk insert never leaks in
