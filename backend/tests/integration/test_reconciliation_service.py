"""`ReconciliationService` (S7 §6), `BreakAgingService` (S7 §7), and `ReconciliationBreak`'s
FR-44 CHECK constraint, against real Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.clock import InMemoryTradingCalendar, MarketClock
from app.core.db import DbRole
from app.core.money import Money, Units
from app.core.uow import SessionRole
from app.integrations.ports import (
    CustodianCashRow,
    CustodianFileSet,
    CustodianPositionRow,
    CustodianTransactionRow,
    CustodianTransactionType,
)
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntryType
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.reconciliation.custodian_file_row import CustodianFileRow
from app.models.reconciliation.reconciliation_break import (
    ReconciliationBreak,
    ReconciliationBreakStatus,
    ReconciliationBreakType,
)
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.reconciliation.break_aging_service import BreakAgingService
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.services.reconciliation.uow import ReconciliationUnitOfWork
from tests.integration.conftest import LEDGER_TABLES, insert_customer, insert_inbound_event

RECONCILIATION_TABLES = [
    *LEDGER_TABLES,
    Security.__table__,
    CustodianFileRow.__table__,
    ReconciliationBreak.__table__,
]

MARKET_DATE = date(2026, 1, 5)  # a Monday, a real trading day
HOLIDAY_DATE = date(2026, 1, 3)  # a Saturday, never a trading day


@pytest.fixture
def reconciliation_tables(owner_engine):
    for table in RECONCILIATION_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield
    with owner_engine.begin() as connection:
        for table in reversed(RECONCILIATION_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


pytestmark = pytest.mark.usefixtures("reconciliation_tables")


def _owner_uow() -> ReconciliationUnitOfWork:
    return ReconciliationUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.OWNER)


def _service(uow: ReconciliationUnitOfWork) -> ReconciliationService:
    return ReconciliationService(
        uow, market_clock=MarketClock(InMemoryTradingCalendar()), now=lambda: datetime.now(UTC)
    )


def _empty_file_set(*, is_simulated: bool = True) -> CustodianFileSet:
    return CustodianFileSet(positions=[], cash=[], transactions=[], is_simulated=is_simulated)


def _insert_security(uow: ReconciliationUnitOfWork) -> uuid.UUID:
    security = Security(
        symbol=f"TST{uuid.uuid4().hex[:8]}", name="Test Co", asset_class=SecurityAssetClass.EQUITY
    )
    uow.session.add(security)
    uow.session.flush()
    return security.id


def _post_position(
    uow: ReconciliationUnitOfWork,
    *,
    customer_id: uuid.UUID,
    security_id: uuid.UUID,
    quantity: Units,
) -> None:
    """Units-only `CORRECTION` entry: establishes a position without also registering as an
    internal transaction the transactions loop would expect a file match for."""
    units_account = Account.create(
        AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security_id
    )
    uow.session.add(units_account)
    uow.session.flush()
    event_id = insert_inbound_event(uow.session)
    PostingService(uow).post(
        entry_type=JournalEntryType.CORRECTION,
        effective_date=MARKET_DATE,
        source_event_id=event_id,
        legs=[PostingLeg(account_id=units_account.id, quantity_units=quantity)],
    )


def _post_settled_deposit(
    uow: ReconciliationUnitOfWork, *, customer_id: uuid.UUID, amount: Money
) -> None:
    """Same `CORRECTION`-not-`DEPOSIT` reasoning as `_post_position`, isolating the cash case."""
    cash_account = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity_account = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    uow.session.add_all([cash_account, equity_account])
    uow.session.flush()
    event_id = insert_inbound_event(uow.session)
    PostingService(uow).post(
        entry_type=JournalEntryType.CORRECTION,
        effective_date=MARKET_DATE,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=cash_account.id, amount_money=amount),
            PostingLeg(account_id=equity_account.id, amount_money=-amount),
        ],
    )


def _post_observable_transaction(
    uow: ReconciliationUnitOfWork, *, customer_id: uuid.UUID, amount: Money, source_event_id: str
) -> None:
    """A DEPOSIT entry traceable to a `source_event_id`, the join key the transactions loop uses."""
    cash_account = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity_account = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    uow.session.add_all([cash_account, equity_account])
    uow.session.flush()
    event_id = insert_inbound_event(uow.session, source_event_id=source_event_id)
    PostingService(uow).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=MARKET_DATE,
        source_event_id=event_id,
        legs=[
            PostingLeg(account_id=cash_account.id, amount_money=amount),
            PostingLeg(account_id=equity_account.id, amount_money=-amount),
        ],
    )


# --- holiday short-circuit (S7 §6/§10 case 1, ADR 12) ----------------------------------------


def test_holiday_is_never_a_break_and_persists_no_raw_rows() -> None:
    with _owner_uow() as uow:
        breaks = _service(uow).run_morning_reconciliation(
            market_date=HOLIDAY_DATE, file_set=_empty_file_set()
        )
        uow.commit()

        assert breaks == []
        assert uow.session.query(CustodianFileRow).count() == 0


# --- positions (S7 §4/§6) --------------------------------------------------------------------


def test_positions_matching_the_file_open_no_break() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow)
        _post_position(uow, customer_id=customer_id, security_id=security_id, quantity=Units("10"))

        file_set = CustodianFileSet(
            positions=[
                CustodianPositionRow(
                    customer_id=customer_id,
                    security_id=security_id,
                    quantity=Units("10"),
                    as_of_date=MARKET_DATE,
                )
            ],
            cash=[],
            transactions=[],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert breaks == []


def test_fr32_live_fire_a_single_tampered_position_opens_exactly_one_correct_break() -> None:
    """S7 §11 (FR-32): tamper one position; exactly one break opens with correct expected/actual."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow)
        _post_position(uow, customer_id=customer_id, security_id=security_id, quantity=Units("10"))

        # The tamper: the file says 7, Trueup's own ledger says 10.
        file_set = CustodianFileSet(
            positions=[
                CustodianPositionRow(
                    customer_id=customer_id,
                    security_id=security_id,
                    quantity=Units("7"),
                    as_of_date=MARKET_DATE,
                )
            ],
            cash=[],
            transactions=[],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert len(breaks) == 1
        break_row = breaks[0]
        assert break_row.break_type is ReconciliationBreakType.POSITION_MISMATCH
        assert break_row.customer_id == customer_id
        assert break_row.expected == {"security_id": str(security_id), "quantity": str(Units("10"))}
        assert break_row.actual == {"security_id": str(security_id), "quantity": str(Units("7"))}


def test_a_position_present_only_in_the_file_is_a_break() -> None:
    """S7 §6: a position the file reports but Trueup never heard of is a mismatch, not ignored."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow)
        # No internal position posted at all.

        file_set = CustodianFileSet(
            positions=[
                CustodianPositionRow(
                    customer_id=customer_id,
                    security_id=security_id,
                    quantity=Units("5"),
                    as_of_date=MARKET_DATE,
                )
            ],
            cash=[],
            transactions=[],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert len(breaks) == 1
        assert breaks[0].break_type is ReconciliationBreakType.POSITION_MISMATCH
        assert breaks[0].expected == {"security_id": str(security_id), "quantity": str(Units("0"))}
        assert breaks[0].actual == {"security_id": str(security_id), "quantity": str(Units("5"))}


# --- cash (S7 §4/§6) -------------------------------------------------------------------------


def test_cash_matching_the_file_opens_no_break() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.session.add(CustomerCashLock(customer_id=customer_id))
        _post_settled_deposit(uow, customer_id=customer_id, amount=Money("500.00"))

        file_set = CustodianFileSet(
            positions=[],
            cash=[
                CustodianCashRow(
                    customer_id=customer_id, settled_cash=Money("500.00"), as_of_date=MARKET_DATE
                )
            ],
            transactions=[],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert breaks == []


def test_cash_mismatch_opens_a_break_with_both_values() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        uow.session.add(CustomerCashLock(customer_id=customer_id))
        _post_settled_deposit(uow, customer_id=customer_id, amount=Money("500.00"))

        file_set = CustodianFileSet(
            positions=[],
            cash=[
                CustodianCashRow(
                    customer_id=customer_id, settled_cash=Money("450.00"), as_of_date=MARKET_DATE
                )
            ],
            transactions=[],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert len(breaks) == 1
        assert breaks[0].break_type is ReconciliationBreakType.CASH_MISMATCH
        assert breaks[0].customer_id == customer_id
        assert breaks[0].expected == {"settled_cash": str(Money("500.00"))}
        assert breaks[0].actual == {"settled_cash": str(Money("450.00"))}


# --- transactions (S7 §4/§6) ------------------------------------------------------------------


def test_a_matched_transaction_opens_no_break() -> None:
    """A real deposit is both a cash fact and a transaction fact; the file set matches both."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        _post_observable_transaction(
            uow, customer_id=customer_id, amount=Money("100.00"), source_event_id="txn-1"
        )

        file_set = CustodianFileSet(
            positions=[],
            cash=[
                CustodianCashRow(
                    customer_id=customer_id, settled_cash=Money("100.00"), as_of_date=MARKET_DATE
                )
            ],
            transactions=[
                CustodianTransactionRow(
                    custodian_transaction_id="txn-1",
                    customer_id=customer_id,
                    security_id=None,
                    transaction_type=CustodianTransactionType.DEPOSIT,
                    amount_money=Money("100.00"),
                    quantity=None,
                    effective_date=MARKET_DATE,
                )
            ],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert breaks == []


def test_a_custodian_transaction_with_no_internal_match_is_a_break() -> None:
    """S7 §9's inject_late_dividend shape: a file transaction with no corresponding S1 entry yet."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)

        file_set = CustodianFileSet(
            positions=[],
            cash=[],
            transactions=[
                CustodianTransactionRow(
                    custodian_transaction_id="txn-orphan",
                    customer_id=customer_id,
                    security_id=None,
                    transaction_type=CustodianTransactionType.DIVIDEND,
                    amount_money=Money("25.00"),
                    quantity=None,
                    effective_date=MARKET_DATE,
                )
            ],
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert len(breaks) == 1
        assert breaks[0].break_type is ReconciliationBreakType.UNMATCHED_CUSTODIAN_TRANSACTION
        assert breaks[0].customer_id == customer_id
        assert breaks[0].expected is None


def test_an_internal_transaction_with_no_custodian_match_is_a_break() -> None:
    """Isolates the transactions loop: cash total agrees, but the transaction line is missing."""
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        _post_observable_transaction(
            uow,
            customer_id=customer_id,
            amount=Money("100.00"),
            source_event_id="txn-internal-only",
        )

        file_set = CustodianFileSet(
            positions=[],
            cash=[
                CustodianCashRow(
                    customer_id=customer_id, settled_cash=Money("100.00"), as_of_date=MARKET_DATE
                )
            ],
            transactions=[],  # the transaction line itself is missing from the file
            is_simulated=True,
        )
        breaks = _service(uow).run_morning_reconciliation(
            market_date=MARKET_DATE, file_set=file_set
        )
        uow.commit()

        assert len(breaks) == 1
        assert breaks[0].break_type is ReconciliationBreakType.UNMATCHED_INTERNAL_TRANSACTION
        assert breaks[0].customer_id == customer_id
        assert breaks[0].actual is None


# --- raw row preservation + is_simulated tagging (S7 §3, FR-33) ------------------------------


def test_every_raw_row_is_tagged_is_simulated_per_the_file_set() -> None:
    with _owner_uow() as uow:
        customer_id = insert_customer(uow.session)
        security_id = _insert_security(uow)

        file_set = CustodianFileSet(
            positions=[
                CustodianPositionRow(
                    customer_id=customer_id,
                    security_id=security_id,
                    quantity=Units("1"),
                    as_of_date=MARKET_DATE,
                )
            ],
            cash=[
                CustodianCashRow(
                    customer_id=customer_id, settled_cash=Money("1.00"), as_of_date=MARKET_DATE
                )
            ],
            transactions=[
                CustodianTransactionRow(
                    custodian_transaction_id="txn-1",
                    customer_id=customer_id,
                    security_id=None,
                    transaction_type=CustodianTransactionType.DEPOSIT,
                    amount_money=Money("1.00"),
                    quantity=None,
                    effective_date=MARKET_DATE,
                )
            ],
            is_simulated=True,
        )
        _service(uow).run_morning_reconciliation(market_date=MARKET_DATE, file_set=file_set)
        uow.commit()

        rows = uow.session.query(CustodianFileRow).all()
        assert len(rows) == 3
        assert all(row.is_simulated for row in rows)


# --- BreakAgingService (S7 §7) -----------------------------------------------------------------


def test_break_age_is_now_minus_opened_at() -> None:
    opened_at = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    now = datetime(2026, 1, 4, 12, 0, tzinfo=UTC)
    break_row = ReconciliationBreak(
        break_type=ReconciliationBreakType.CASH_MISMATCH,
        customer_id=uuid.uuid4(),
        opened_at=opened_at,
        import_batch_id=uuid.uuid4(),
    )

    age = BreakAgingService.age(break_row, now=now)

    assert age.days == 3


# --- FR-44: resolved_by CHECK constraint (S7 §5.2/§11) ----------------------------------------


def test_resolved_status_requires_a_non_null_resolved_by_at_the_db_level(db_committing) -> None:
    break_row = ReconciliationBreak(
        break_type=ReconciliationBreakType.CASH_MISMATCH,
        customer_id=uuid.uuid4(),
        opened_at=datetime.now(UTC),
        status=ReconciliationBreakStatus.OPEN,
        import_batch_id=uuid.uuid4(),
    )
    db_committing.add(break_row)
    db_committing.commit()

    break_row.status = ReconciliationBreakStatus.RESOLVED  # resolved_by left null, must fail
    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


def test_resolving_with_a_resolver_is_permitted(db_committing) -> None:
    break_row = ReconciliationBreak(
        break_type=ReconciliationBreakType.CASH_MISMATCH,
        customer_id=uuid.uuid4(),
        opened_at=datetime.now(UTC),
        status=ReconciliationBreakStatus.OPEN,
        import_batch_id=uuid.uuid4(),
    )
    db_committing.add(break_row)
    db_committing.commit()

    break_row.status = ReconciliationBreakStatus.RESOLVED
    break_row.resolved_by = uuid.uuid4()
    break_row.resolved_at = datetime.now(UTC)
    db_committing.commit()  # must not raise
