"""`GET /api/v1/valuation/*` (S4 §7) via the Flask test client.

S4 §9 calls out a `views/` contract test proving `completeness`/`is_provisional` survive from the
service layer into the response body -- this file is that test, exercised through the real HTTP
surface rather than at the schema level alone.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.money import Money
from app.models.identity.staff import Staff, StaffRole
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.marketdata.daily_close import DailyClose
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security
from app.models.marketdata.sub_period_return import SubPeriodReturn
from app.models.marketdata.valuation_run import ValuationRun
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.services.identity.auth import hash_password
from app.services.ledger.posting_service import PostingLeg, PostingService

CUSTOMER_EMAIL = "valuation-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "valuation-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"

VALUATION_TABLES = [
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ValuationRun.__table__,
    SubPeriodReturn.__table__,
]


@pytest.fixture(autouse=True)
def _valuation_tables(owner_engine: Engine) -> Iterator[None]:
    """Function-scoped create-before/drop-after, matching every other test file's convention
    (`tests/integration/conftest.py`'s `ledger_tables`) -- deliberately not a session-scoped
    truncate-between-tests fixture, since these tables (`inbound_event`, `account`, ...) are also
    populated by other sub-projects' own fixtures, and a CASCADE truncate/drop reaching across a
    shared FK graph mid-session risks wiping rows another file's test still depends on.

    Teardown uses raw `DROP TABLE ... IF EXISTS`, not `Table.drop()`: `market_data_source` is one
    Postgres enum shared by two tables (`daily_close`, `market_calendar_cache`), and SQLAlchemy's
    per-Table drop event tries to drop the enum type alongside whichever of the two tables is
    dropped first, failing with `DependentObjectsStillExist` while the other table still
    references it (matches `tests/integration/test_valuation_service.py`'s `valuation_tables`)."""
    for table in VALUATION_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(VALUATION_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}"'))


class _LedgerLikeUow:
    def __init__(self, session: Session) -> None:
        self.session = session

        class _Repo:
            def __init__(self, session: Session) -> None:
                self._session = session

            def add(self, obj: object) -> None:
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


def _register(client: FlaskClient, *, email: str, password: str) -> uuid.UUID:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return uuid.UUID(response.get_json()["id"])


def _login(client: FlaskClient, *, email: str, password: str) -> str:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    csrf_token: str = response.get_json()["csrf_token"]
    return csrf_token


@pytest.fixture
def staff_member(owner_engine: Engine) -> Iterator[Staff]:
    session = Session(bind=owner_engine, expire_on_commit=False)
    staff = Staff(
        email=STAFF_EMAIL, password_hash=hash_password(STAFF_PASSWORD), role=StaffRole.adviser
    )
    session.add(staff)
    session.commit()
    yield staff
    session.close()


def _deposit(owner_engine: Engine, customer_id: uuid.UUID, *, amount: Money, on: date) -> None:
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(CustomerCashLock(customer_id=customer_id))
    cash = Account.create(AccountRole.CASH, customer_id=customer_id)
    equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
    session.add_all([cash, equity])
    session.flush()

    event = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    session.add(event)
    session.flush()

    PostingService(_LedgerLikeUow(session)).post(
        entry_type=JournalEntryType.DEPOSIT,
        effective_date=on,
        source_event_id=event.id,
        legs=[
            PostingLeg(account_id=cash.id, amount_money=amount),
            PostingLeg(account_id=equity.id, amount_money=-amount),
        ],
    )
    session.commit()
    session.close()


# --- balance -------------------------------------------------------------------------------


def test_balance_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/valuation/balance")

    assert response.status_code == 401


def test_balance_happy_path_returns_the_customers_cash(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _deposit(owner_engine, customer_id, amount=Money("1500.00"), on=date(2026, 9, 1))

    response = api_client.get("/api/v1/valuation/balance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_value"] == "1500.0000"
    assert body["completeness"] == "complete"
    assert "as_of_date" in body


def test_balance_with_zero_positions_is_complete_not_an_error(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/valuation/balance")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_value"] == "0.0000"
    assert body["completeness"] == "complete"


def test_balance_is_throttled(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/valuation/balance")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


@pytest.mark.xfail(
    reason=(
        "Blocked on a foundation bug (escalated to main, not S4's to fix): "
        "app/controllers/api/auth.py's load_user() returns its principal from inside a "
        "never-committed UnitOfWork, so UnitOfWork.__exit__ rolls back (expiring every mapped "
        "attribute) before closing (detaching it). Staff.role is a real mapped column, so "
        "app/core/security.py's requires_role() raises DetachedInstanceError on "
        "`current_user.role` for every staff session on every request after login."
    ),
    strict=False,
)
def test_balance_for_staff_without_customer_id_is_a_validation_error(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    login_response = api_client.post(
        "/api/v1/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD}
    )
    assert login_response.status_code == 200
    pending_csrf = login_response.get_json()["csrf_token"]

    secret = api_client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": pending_csrf}
    ).get_json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": pending_csrf}
    )
    assert verify.status_code == 200

    response = api_client.get("/api/v1/valuation/balance")

    assert response.status_code == 422


@pytest.mark.xfail(
    reason=(
        "Blocked on the same foundation bug as "
        "test_balance_for_staff_without_customer_id_is_a_validation_error -- see its reason."
    ),
    strict=False,
)
def test_balance_for_staff_with_customer_id_sees_that_customers_balance(
    api_client: FlaskClient, staff_member: Staff, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _deposit(owner_engine, customer_id, amount=Money("750.00"), on=date(2026, 9, 1))

    login_response = api_client.post(
        "/api/v1/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD}
    )
    pending_csrf = login_response.get_json()["csrf_token"]
    secret = api_client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": pending_csrf}
    ).get_json()["secret"]
    code = pyotp.TOTP(secret).now()
    api_client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": pending_csrf}
    )

    response = api_client.get(f"/api/v1/valuation/balance?customer_id={customer_id}")

    assert response.status_code == 200
    assert response.get_json()["total_value"] == "750.0000"


# --- returns -------------------------------------------------------------------------------


def test_returns_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(
        "/api/v1/valuation/returns?period_start=2026-09-01&period_end=2026-09-10"
    )

    assert response.status_code == 401


def test_returns_rejects_missing_period_params(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/valuation/returns")

    assert response.status_code == 422


def test_returns_happy_path_is_zero_with_no_market_exposure(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _deposit(owner_engine, customer_id, amount=Money("1000.00"), on=date(2026, 9, 1))

    response = api_client.get(
        "/api/v1/valuation/returns?period_start=2026-09-01&period_end=2026-09-10"
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["twr"] == "0.0000000000"
    assert body["is_provisional"] is False
    assert body["period_start"] == "2026-09-01"
    assert body["period_end"] == "2026-09-10"


# --- history ---------------------------------------------------------------------------------


def test_history_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/valuation/history")

    assert response.status_code == 401


def test_history_happy_path_includes_the_deposit(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _deposit(owner_engine, customer_id, amount=Money("400.00"), on=date(2026, 9, 1))

    response = api_client.get("/api/v1/valuation/history")

    assert response.status_code == 200
    entries = response.get_json()["entries"]
    # One posting leg per row: the deposit's cash leg and its customer_equity counter-leg.
    assert len(entries) == 2
    assert all(entry["entry_type"] == "deposit" for entry in entries)
    amounts = {entry["amount_money"] for entry in entries}
    assert amounts == {"400.0000", "-400.0000"}
