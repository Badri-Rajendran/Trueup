"""`GET /api/v1/admin/customers`, `GET /api/v1/admin/customers/<id>`,
`GET /api/v1/admin/customers/<id>/fees` (S8 §4 rows 1/2/6) via the Flask test client: search,
the aggregated detail view (balance agreeing with `/valuation/balance`, an open break surfaced
prominently per S8 §6 case 2), the fees re-export, authn/authz, and throttling.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.money import Money
from app.models.fees.dunning_state import DunningState
from app.models.fees.fee_accrual import FeeAccrual
from app.models.fees.fee_charge import FeeCharge
from app.models.fees.high_water_mark import HighWaterMark
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
from app.models.reconciliation.reconciliation_break import (
    ReconciliationBreak,
    ReconciliationBreakType,
)
from app.services.identity.auth import hash_password
from app.services.ledger.posting_service import PostingLeg, PostingService

STAFF_EMAIL = "admin-customers-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"
CUSTOMER_PASSWORD = "correct-horse-battery"

ADMIN_CUSTOMERS_TABLES = [
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
    ReconciliationBreak.__table__,
    HighWaterMark.__table__,
    FeeAccrual.__table__,
    FeeCharge.__table__,
    DunningState.__table__,
]


@pytest.fixture(autouse=True)
def _admin_customers_tables(owner_engine: Engine) -> Iterator[None]:
    for table in ADMIN_CUSTOMERS_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(ADMIN_CUSTOMERS_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


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


def _register(client: FlaskClient, *, email: str, password: str = CUSTOMER_PASSWORD) -> uuid.UUID:
    response = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201
    return uuid.UUID(response.get_json()["id"])


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


def _staff_login_with_mfa(client: FlaskClient) -> None:
    login_response = client.post(
        "/api/v1/auth/login", json={"email": STAFF_EMAIL, "password": STAFF_PASSWORD}
    )
    assert login_response.status_code == 200
    pending_csrf = login_response.get_json()["csrf_token"]
    secret = client.post(
        "/api/v1/auth/mfa/enroll", headers={"X-CSRFToken": pending_csrf}
    ).get_json()["secret"]
    code = pyotp.TOTP(secret).now()
    verify = client.post(
        "/api/v1/auth/mfa/verify", json={"code": code}, headers={"X-CSRFToken": pending_csrf}
    )
    assert verify.status_code == 200


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


def _open_break(owner_engine: Engine, customer_id: uuid.UUID) -> None:
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        ReconciliationBreak(
            break_type=ReconciliationBreakType.CASH_MISMATCH,
            customer_id=customer_id,
            expected={"cash": "100.00"},
            actual={"cash": "90.00"},
            opened_at=datetime(2026, 1, 1, tzinfo=UTC),
            import_batch_id=uuid.uuid4(),
        )
    )
    session.commit()
    session.close()


# --- GET /api/v1/admin/customers ------------------------------------------------------------


def test_list_customers_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/admin/customers?query=a")

    assert response.status_code == 401


def test_list_customers_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    _register(api_client, email="plain-customer@trueup.example")
    api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain-customer@trueup.example", "password": CUSTOMER_PASSWORD},
    )

    response = api_client.get("/api/v1/admin/customers?query=a")

    assert response.status_code == 403


def test_list_customers_requires_a_query(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    _staff_login_with_mfa(api_client)

    response = api_client.get("/api/v1/admin/customers")

    assert response.status_code == 422


def test_list_customers_matches_email_case_insensitively(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    _register(api_client, email="match-me@trueup.example")
    _register(api_client, email="no-match@trueup.example")
    _staff_login_with_mfa(api_client)

    response = api_client.get("/api/v1/admin/customers?query=MATCH-ME")

    assert response.status_code == 200
    body = response.get_json()
    assert [c["email"] for c in body["customers"]] == ["match-me@trueup.example"]
    assert body["next_cursor"] is None


def test_list_customers_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/admin/customers?query=a")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /api/v1/admin/customers/<id> -------------------------------------------------------


def test_get_customer_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}")

    assert response.status_code == 401


def test_get_customer_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    _register(api_client, email="plain-customer-2@trueup.example")
    api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain-customer-2@trueup.example", "password": CUSTOMER_PASSWORD},
    )

    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}")

    assert response.status_code == 403


def test_get_customer_not_found(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}")

    assert response.status_code == 404


def test_get_customer_balance_agrees_with_the_valuation_endpoint(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id = _register(api_client, email="balance-check@trueup.example")
    _deposit(owner_engine, customer_id, amount=Money("2500.00"), on=date(2026, 1, 5))
    _staff_login_with_mfa(api_client)

    admin_response = api_client.get(f"/api/v1/admin/customers/{customer_id}")
    valuation_response = api_client.get(f"/api/v1/valuation/balance?customer_id={customer_id}")

    assert admin_response.status_code == 200
    assert valuation_response.status_code == 200
    admin_body = admin_response.get_json()
    valuation_body = valuation_response.get_json()
    assert admin_body["balance"] == valuation_body
    assert admin_body["open_reconciliation_breaks"] == []


def test_get_customer_surfaces_an_open_reconciliation_break(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id = _register(api_client, email="broken-customer@trueup.example")
    _deposit(owner_engine, customer_id, amount=Money("100.00"), on=date(2026, 1, 5))
    _open_break(owner_engine, customer_id)
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/admin/customers/{customer_id}")

    assert response.status_code == 200
    breaks = response.get_json()["open_reconciliation_breaks"]
    assert len(breaks) == 1
    assert breaks[0]["break_type"] == "cash_mismatch"
    assert breaks[0]["status"] == "open"


def test_get_customer_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(61):
        last_response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /api/v1/admin/customers/<id>/fees --------------------------------------------------


def test_get_customer_fees_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}/fees")

    assert response.status_code == 401


def test_get_customer_fees_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    _register(api_client, email="plain-customer-3@trueup.example")
    api_client.post(
        "/api/v1/auth/login",
        json={"email": "plain-customer-3@trueup.example", "password": CUSTOMER_PASSWORD},
    )

    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}/fees")

    assert response.status_code == 403


def test_get_customer_fees_not_found(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}/fees")

    assert response.status_code == 404


def test_get_customer_fees_matches_the_fees_endpoint(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    customer_id = _register(api_client, email="fees-check@trueup.example")
    _staff_login_with_mfa(api_client)

    admin_response = api_client.get(f"/api/v1/admin/customers/{customer_id}/fees")
    fees_response = api_client.get(f"/api/v1/fees?customer_id={customer_id}")

    assert admin_response.status_code == 200
    assert fees_response.status_code == 200
    assert admin_response.get_json() == fees_response.get_json()


def test_get_customer_fees_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(31):
        last_response = api_client.get(f"/api/v1/admin/customers/{uuid.uuid4()}/fees")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
