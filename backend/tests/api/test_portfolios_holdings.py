"""`GET /api/v1/portfolios/holdings` (Portfolio page redesign, ADR 26 context) via the Flask test
client -- the customer-facing counterpart to `tests/api/test_admin_rebalance_api.py`'s adviser-only
route, built on the same `DriftEvaluationService` (S9 §4).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.core.clock import MARKET_TIMEZONE
from app.core.money import Money, Price, Units
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.marketdata.daily_close import DailyClose, DailyCloseStatus, MarketDataSource
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.rebalance.target_weight import TargetWeight
from app.services.ledger.posting_service import PostingLeg, PostingService

CUSTOMER_EMAIL = "holdings-customer@trueup.example"
CUSTOMER_EMAIL_2 = "holdings-customer-2@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
MARKET_DATE = datetime.now(UTC).astimezone(MARKET_TIMEZONE).date()
"""Matches `MarketClock.market_date()`'s own computation; the controller has no injectable clock."""

HOLDINGS_TABLES = [
    InboundEvent.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    Security.__table__,
    DailyClose.__table__,
    ModelPortfolio.__table__,
    TargetWeight.__table__,
    CustomerModelAssignment.__table__,
]


@pytest.fixture(autouse=True)
def _holdings_tables(owner_engine: Engine) -> Iterator[None]:
    for table in HOLDINGS_TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(HOLDINGS_TABLES):
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


def _post(session: Session, *, entry_type: JournalEntryType, legs: list[PostingLeg]) -> None:
    event = InboundEvent(
        source=InboundEventSource.CUSTODIAN_FILE,
        source_event_id=str(uuid.uuid4()),
        payload={},
        signature_verified=True,
    )
    session.add(event)
    session.flush()
    PostingService(_LedgerLikeUow(session)).post(
        entry_type=entry_type, effective_date=MARKET_DATE, source_event_id=event.id, legs=legs
    )


def _seed_customer_with_holding(
    owner_engine: Engine,
    customer_id: uuid.UUID,
    *,
    seed_close: bool = True,
    symbol: str = "ONTGT",
) -> tuple[uuid.UUID, uuid.UUID]:
    """100 shares of one security, deposit fully spent -- on-target for a 100% model."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        customer.kyc_status = KycStatus.approved
        customer.account_approval_status = AccountApprovalStatus.approved
        session.add(CustomerCashLock(customer_id=customer_id))

        security = Security(
            symbol=symbol, name=f"{symbol} Co.", asset_class=SecurityAssetClass.EQUITY
        )
        session.add(security)
        session.flush()
        if seed_close:
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

        _post(
            session,
            entry_type=JournalEntryType.DEPOSIT,
            legs=[
                PostingLeg(account_id=cash.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=equity.id, amount_money=Money("-10000.00")),
            ],
        )
        _post(
            session,
            entry_type=JournalEntryType.TRADE_BUY,
            legs=[
                PostingLeg(account_id=units.id, quantity_units=Units("100")),
                PostingLeg(account_id=cost.id, amount_money=Money("10000.00")),
                PostingLeg(account_id=cash.id, amount_money=Money("-10000.00")),
            ],
        )

        session.commit()
        return security.id, cash.id
    finally:
        session.close()


def _assign_model(
    owner_engine: Engine,
    customer_id: uuid.UUID,
    *,
    target_security_id: uuid.UUID,
    weight_pct: Decimal = Decimal("1.0000"),
) -> uuid.UUID:
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        model = ModelPortfolio(name="Fully Invested")
        session.add(model)
        session.flush()
        session.add(
            TargetWeight(
                model_portfolio_id=model.id,
                security_id=target_security_id,
                weight_pct=weight_pct,
            )
        )
        session.add(
            CustomerModelAssignment(
                customer_id=customer_id, model_portfolio_id=model.id, assigned_at=MARKET_DATE
            )
        )
        session.commit()
        return model.id
    finally:
        session.close()


# --- GET /portfolios/holdings ----------------------------------------------------------------


def test_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/portfolios/holdings")

    assert response.status_code == 401


def test_happy_path_returns_holdings_with_symbol_and_completeness(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    security_id, _cash_id = _seed_customer_with_holding(owner_engine, customer_id)
    model_id = _assign_model(owner_engine, customer_id, target_security_id=security_id)

    response = api_client.get("/api/v1/portfolios/holdings")

    assert response.status_code == 200
    body = response.get_json()
    assert body["customer_id"] == str(customer_id)
    assert body["completeness"] == "complete"
    assert body["total_value"] == "10000.0000"
    holdings_by_security = {h["security_id"]: h for h in body["holdings"]}
    security_line = holdings_by_security[str(security_id)]
    assert security_line["symbol"] == "ONTGT"
    assert security_line["units"] == "100.000000"
    assert security_line["price"] == "100.000000"
    assert security_line["market_value"] == "10000.0000"
    assert Decimal(security_line["target_weight_pct"]) == Decimal("1.0000")
    assert Decimal(security_line["drift_pct"]) == Decimal("0.0000")
    assert security_line["is_flagged"] is False
    cash_line = holdings_by_security[None]
    assert cash_line["symbol"] is None
    assert cash_line["units"] is None
    assert cash_line["price"] is None
    del model_id


def test_no_assigned_model_is_a_distinguishable_404(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/holdings")

    assert response.status_code == 404
    assert response.get_json()["code"] == "no_model_assigned"


def test_partial_completeness_is_reported_explicitly_not_as_an_empty_list(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    # No confirmed close for the held security -- valuation is partial (S4 §4).
    security_id, _cash_id = _seed_customer_with_holding(owner_engine, customer_id, seed_close=False)
    _assign_model(owner_engine, customer_id, target_security_id=security_id)

    response = api_client.get("/api/v1/portfolios/holdings")

    assert response.status_code == 200
    body = response.get_json()
    assert body["completeness"] == "partial"
    assert body["holdings"] == []


def test_security_dropped_from_model_still_appears_with_zero_target_weight(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    held_security_id, _cash_id = _seed_customer_with_holding(
        owner_engine, customer_id, symbol="DROPPED"
    )
    # Target a different security the customer holds none of -- `held_security_id` is fully
    # dropped from the model, but must still surface (S9 §8 item 4).
    session = Session(bind=owner_engine, expire_on_commit=False)
    other_security = Security(
        symbol="TARGETONLY", name="Target Only Co.", asset_class=SecurityAssetClass.EQUITY
    )
    session.add(other_security)
    session.flush()
    session.add(
        DailyClose(
            security_id=other_security.id,
            market_date=MARKET_DATE,
            close_price=Price("50.00"),
            source=MarketDataSource.LIVE,
            status=DailyCloseStatus.CONFIRMED,
        )
    )
    session.commit()
    other_security_id = other_security.id
    session.close()
    _assign_model(owner_engine, customer_id, target_security_id=other_security_id)

    response = api_client.get("/api/v1/portfolios/holdings")

    assert response.status_code == 200
    body = response.get_json()
    holdings_by_security = {h["security_id"]: h for h in body["holdings"]}
    dropped_line = holdings_by_security[str(held_security_id)]
    assert Decimal(dropped_line["target_weight_pct"]) == Decimal("0")
    assert dropped_line["market_value"] == "10000.0000"


def test_another_customers_holdings_are_isolated(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    customer_id = _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    security_id, _cash_id = _seed_customer_with_holding(owner_engine, customer_id, symbol="ALPHA")
    _assign_model(owner_engine, customer_id, target_security_id=security_id)

    _register(api_client, email=CUSTOMER_EMAIL_2, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL_2, password=CUSTOMER_PASSWORD)

    response = api_client.get("/api/v1/portfolios/holdings")

    # The second customer has no assignment of their own -- never customer one's data.
    assert response.status_code == 404
    assert response.get_json()["code"] == "no_model_assigned"


def test_is_throttled(api_client: FlaskClient) -> None:
    _register(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)
    _login(api_client, email=CUSTOMER_EMAIL, password=CUSTOMER_PASSWORD)

    last_response = None
    for _ in range(61):
        last_response = api_client.get("/api/v1/portfolios/holdings")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
