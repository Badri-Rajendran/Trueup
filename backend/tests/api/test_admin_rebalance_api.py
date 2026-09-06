"""`GET /api/v1/admin/rebalance/<customer_id>` (S9, admin visibility only) via the Flask test client.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.clock import MARKET_TIMEZONE
from app.core.money import Money, Price, Units
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.identity.staff import Staff, StaffRole
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.market_calendar_cache import MarketCalendarCache
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.identity.auth import hash_password
from app.services.ledger.posting_service import PostingLeg, PostingService

CUSTOMER_EMAIL = "admin-rebalance-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
STAFF_EMAIL = "admin-rebalance-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"
MARKET_DATE = datetime.now(UTC).astimezone(MARKET_TIMEZONE).date()
"""Matches `MarketClock.market_date()`'s own computation; the controller has no injectable clock."""

ADMIN_REBALANCE_TABLES = [
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    Security.__table__,
    MarketCalendarCache.__table__,
    DailyClose.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
    CustomerModelAssignment.__table__,
]


@pytest.fixture(autouse=True)
def _admin_rebalance_tables(owner_engine: Engine) -> Iterator[None]:
    for table in ADMIN_REBALANCE_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(ADMIN_REBALANCE_TABLES):
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


def _seed_customer_with_holding(
    owner_engine: Engine, customer_id: uuid.UUID
) -> tuple[uuid.UUID, uuid.UUID]:
    """100 shares of one security and $0 cash left over — exactly on target for a 100% model (S9 §3.2)."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        customer.kyc_status = KycStatus.approved
        customer.account_approval_status = AccountApprovalStatus.approved
        session.add(CustomerCashLock(customer_id=customer_id))

        security = Security(
            symbol="ONTGT", name="On Target Co.", asset_class=SecurityAssetClass.EQUITY
        )
        session.add(security)
        session.flush()
        session.add(
            DailyClose(
                security_id=security.id,
                market_date=MARKET_DATE,
                close_price=Price("100.00"),
                source=MarketDataSource.LIVE,
                status=DailyCloseStatus.CONFIRMED,
            )
        )

        cash = Account.create(AccountRole.CASH, customer_id=customer_id)
        equity = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
        units = Account.create(
            AccountRole.POSITION_UNITS, customer_id=customer_id, security_id=security.id
        )
        cost = Account.create(
            AccountRole.POSITION_COST, customer_id=customer_id, security_id=security.id
        )
        session.add_all([cash, equity, units, cost])
        session.flush()

        event_one = InboundEvent(
            source=InboundEventSource.CUSTODIAN_FILE,
            source_event_id=str(uuid.uuid4()),
            payload={},
            signature_verified=True,
        )
        session.add(event_one)
        session.flush()
        PostingService(_LedgerLikeUow(session)).post(
            entry_type=JournalEntryType.DEPOSIT,
            effective_date=MARKET_DATE,
            source_event_id=event_one.id,
            legs=[
                PostingLeg(account_id=cash.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=equity.id, amount_money=Money("-10000.00")),
            ],
        )
        event_two = InboundEvent(
            source=InboundEventSource.CUSTODIAN_FILE,
            source_event_id=str(uuid.uuid4()),
            payload={},
            signature_verified=True,
        )
        session.add(event_two)
        session.flush()
        PostingService(_LedgerLikeUow(session)).post(
            entry_type=JournalEntryType.TRADE_BUY,
            effective_date=MARKET_DATE,
            source_event_id=event_two.id,
            legs=[
                PostingLeg(account_id=units.id, quantity_units=Units("100")),
                PostingLeg(account_id=cost.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=cash.id, amount_money=Money("-10000.00")),
            ],
        )

        model = ModelPortfolio(name="Fully Invested")
        session.add(model)
        session.flush()
        session.add(
            TargetWeight(
                model_portfolio_id=model.id, security_id=security.id, weight_pct=Decimal("1.0000")
            )
        )
        session.add(
            CustomerModelAssignment(
                customer_id=customer_id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
            )
        )
        session.commit()
        return model.id, security.id
    finally:
        session.close()


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/admin/rebalance/{uuid.uuid4()}")

    assert response.status_code == 401


def test_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get(f"/api/v1/admin/rebalance/{uuid.uuid4()}")

    assert response.status_code == 403


def test_staff_sees_the_customers_drift_status(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    model_id, security_id = _seed_customer_with_holding(owner_engine, customer_id)
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/admin/rebalance/{customer_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["customer_id"] == str(customer_id)
    assert body["model_portfolio_id"] == str(model_id)
    assert body["completeness"] == "complete"
    assert body["total_value"] == "10000.0000"
    holdings_by_security = {h["security_id"]: h for h in body["holdings"]}
    assert holdings_by_security[str(security_id)]["is_flagged"] is False
    cash_entry = holdings_by_security[None]
    assert cash_entry["is_flagged"] is False


def test_staff_gets_404_for_a_customer_with_no_assigned_model(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _staff_login_with_mfa(api_client)

    response = api_client.get(f"/api/v1/admin/rebalance/{customer_id}")

    assert response.status_code == 404


def test_is_throttled(api_client: FlaskClient, staff_member: Staff) -> None:
    _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(61):
        last_response = api_client.get(f"/api/v1/admin/rebalance/{uuid.uuid4()}")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
