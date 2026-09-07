"""`POST/GET /api/v1/orders*` (S3 §6) via the Flask test client: happy path, validation, authn/
authz/ownership, and NFR-14's idempotency replay.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from werkzeug.test import TestResponse

from app.controllers.api import orders as orders_controller
from app.core.money import Money, Price, Units
from app.integrations.fake.fake_broker import FakeBrokerAdapter
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry, JournalEntryType
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.marketdata.security import Security, SecurityAssetClass
from app.models.ops.admin_audit_log import AdminAuditLog
from app.models.ops.idempotency_key import IdempotencyKey
from app.models.ops.inbound_event import InboundEvent, InboundEventSource
from app.models.ops.job_outbox import JobOutbox
from app.models.orders.approval_hold import (
    ApprovalHold,
    ApprovalHoldReleaseReason,
    ApprovalHoldStatus,
)
from app.models.orders.order import Order, OrderStatus
from app.models.orders.order_event import OrderEvent, OrderEventType
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.orders.order_service import CustomerNotEligibleError

CUSTOMER_EMAIL = "order-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
# `security_id` must name a real securities-catalogue row (S5); seeded once here.
SECURITY_ID = uuid.uuid4()
SECURITY_SYMBOL = "AAPL"
DEFAULT_TEST_CASH = Money("1000000.00")


@pytest.fixture(scope="session", autouse=True)
def _order_tables(owner_engine: Engine) -> Iterator[None]:
    tables = [
        Security.__table__,
        InboundEvent.__table__,
        Account.__table__,
        JournalEntry.__table__,
        Posting.__table__,
        SettlementObligation.__table__,
        CustomerCashLock.__table__,
        Order.__table__,
        OrderEvent.__table__,
        ApprovalHold.__table__,
        TaxLot.__table__,
        LotConsumption.__table__,
        WashSaleAdjustment.__table__,
        IdempotencyKey.__table__,
        JobOutbox.__table__,
        AdminAuditLog.__table__,
    ]
    for table in tables:
        table.create(bind=owner_engine, checkfirst=True)
    session = Session(bind=owner_engine, expire_on_commit=False)
    session.add(
        Security(
            id=SECURITY_ID,
            symbol=SECURITY_SYMBOL,
            name="Apple Inc.",
            asset_class=SecurityAssetClass.EQUITY,
        )
    )
    session.commit()
    session.close()
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(tables):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture(autouse=True)
def _clean_order_tables(owner_engine: Engine, _order_tables: None) -> Iterator[None]:
    yield None
    with owner_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE approval_hold, wash_sale_adjustment, lot_consumption, tax_lot, "
                "order_event, \"order\", customer_cash_lock, "
                "idempotency_key, job_outbox, admin_audit_log, settlement_obligation, posting, "
                "journal_entry, account, inbound_event RESTART IDENTITY CASCADE"
            )
        )


class _LedgerLikeUow:
    """Duck-typed stand-in for `LedgerUnitOfWork`, matching `test_cash_policy.py`'s fixture
    helper."""

    def __init__(self, session: Session) -> None:
        self.session = session

        class _Repo:
            def __init__(self, session: Session) -> None:
                self._session = session

            def add(self, obj: object) -> None:
                self._session.add(obj)

        self.journal_entries = _Repo(session)
        self.postings = _Repo(session)


def _register_and_approve_customer(
    client: FlaskClient,
    owner_engine: Engine,
    *,
    email: str = CUSTOMER_EMAIL,
    cash: Money = DEFAULT_TEST_CASH,
) -> uuid.UUID:
    """Registers, grants KYC/account approval, and posts a settled deposit so the F1
    investable-cash check passes."""
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": CUSTOMER_PASSWORD}
    )
    assert response.status_code == 201
    customer_id = uuid.UUID(response.get_json()["id"])

    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        customer.kyc_status = KycStatus.approved
        customer.account_approval_status = AccountApprovalStatus.approved
        session.add(CustomerCashLock(customer_id=customer_id))
        if cash > Money("0.00"):
            cash_account = Account.create(AccountRole.CASH, customer_id=customer_id)
            equity_account = Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer_id)
            session.add_all([cash_account, equity_account])
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
                effective_date=date(2026, 1, 1),
                source_event_id=event.id,
                legs=[
                    PostingLeg(account_id=cash_account.id, amount_money=cash),
                    PostingLeg(account_id=equity_account.id, amount_money=-cash),
                ],
            )
        session.commit()
    finally:
        session.close()
    return customer_id


def _login(client: FlaskClient, *, email: str = CUSTOMER_EMAIL) -> TestResponse:
    return client.post(
        "/api/v1/auth/login", json={"email": email, "password": CUSTOMER_PASSWORD}
    )


def _authed_client(
    client: FlaskClient,
    owner_engine: Engine,
    *,
    email: str = CUSTOMER_EMAIL,
    cash: Money = DEFAULT_TEST_CASH,
) -> tuple[FlaskClient, str]:
    _register_and_approve_customer(client, owner_engine, email=email, cash=cash)
    login_response = _login(client, email=email)
    assert login_response.status_code == 200
    return client, login_response.get_json()["csrf_token"]


def _create_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "security_id": str(SECURITY_ID),
        "side": "buy",
        "quantity": "10",
        "reference_price": "100.00",
    }
    payload.update(overrides)
    return payload


def _advance_order_to_submitted(
    owner_engine: Engine, order_id: uuid.UUID, *, broker_order_id: str = "fake-broker-order-1"
) -> None:
    """Directly synthesizes the `submitted` event/projection/hold-release
    `OrderService.submit_to_broker` would produce -- API tests never run the outbox worker that
    actually calls it."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        order = session.get(Order, order_id)
        assert order is not None
        session.add(
            OrderEvent(
                order_id=order_id,
                seq=1,
                event_type=OrderEventType.SUBMITTED,
                payload={"broker_order_id": broker_order_id},
            )
        )
        order.status = OrderStatus.SUBMITTED
        hold = session.query(ApprovalHold).filter_by(order_id=order_id).one_or_none()
        if hold is not None and hold.status is ApprovalHoldStatus.ACTIVE:
            hold.status = ApprovalHoldStatus.RELEASED
            hold.released_at = datetime.now(UTC)
            hold.release_reason = ApprovalHoldReleaseReason.APPROVED_AND_SUBMITTED
        session.commit()
    finally:
        session.close()


def _record_fill(
    owner_engine: Engine,
    order_id: uuid.UUID,
    *,
    seq: int,
    execution_id: str,
    quantity: str,
    price: str,
    status: OrderStatus = OrderStatus.FILLED,
) -> None:
    """Directly inserts a `fill` `order_event` -- fills arrive over the trade-updates websocket
    (ADR 22), never through this HTTP API."""
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        order = session.get(Order, order_id)
        assert order is not None
        session.add(
            OrderEvent(
                order_id=order_id,
                seq=seq,
                event_type=OrderEventType.FILL,
                execution_id=execution_id,
                payload={"quantity": quantity, "price": price},
            )
        )
        order.status = status
        order.filled_quantity = Units(quantity)
        order.average_fill_price = Price(price)
        session.commit()
    finally:
        session.close()


# --- create: happy path --------------------------------------------------------------------


def test_create_order_at_or_below_threshold_is_approved_immediately(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "approved"
    assert body["side"] == "buy"
    assert body["client_order_id"].startswith("trueup-")


def test_create_order_above_threshold_requires_approval(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="1000", reference_price="100.00"),  # $100,000 notional
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "awaiting_approval"


# --- create: cash policy (S0 §10.1) ---------------------------------------------------------


def test_create_order_rejects_a_buy_exceeding_investable_cash(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine, cash=Money("0.00"))

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(),  # 10 units @ $100 = $1,000 notional; investable is $0
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "insufficient_investable_cash"


def test_create_order_within_investable_cash_still_succeeds(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine, cash=Money("1000.00"))

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(),  # 10 units @ $100 = $1,000 notional; investable is exactly $1,000
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201


# --- create: idempotency (NFR-14) ----------------------------------------------------------


def test_create_order_replays_the_same_response_for_a_repeated_idempotency_key(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    key = str(uuid.uuid4())
    payload = _create_payload()

    first = client.post(
        "/api/v1/orders",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/orders",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json()["id"] == second.get_json()["id"]


def test_create_order_rejects_a_reused_key_with_a_different_body(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    key = str(uuid.uuid4())

    first = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    second = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="99"),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 409


def test_create_order_without_an_idempotency_key_is_rejected(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders", json=_create_payload(), headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422


# --- create: validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"side": "not-a-side"},
        {"quantity": "not-a-number"},
        {"security_id": "not-a-uuid"},
    ],
)
def test_create_order_rejects_invalid_input(
    api_client: FlaskClient, owner_engine: Engine, overrides: dict[str, Any]
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(**overrides),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422


# --- create: authn/authz --------------------------------------------------------------------


def test_create_order_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 400  # CSRFProtect rejects first, matching auth.py's precedent


# --- approve ----------------------------------------------------------------------------------


def test_approve_transitions_an_awaiting_approval_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="1000", reference_price="100.00"),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.post(
        f"/api/v1/orders/{order_id}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "approved"


def test_approve_a_nonexistent_order_returns_not_found(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        f"/api/v1/orders/{uuid.uuid4()}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 404


def test_approve_an_already_approved_order_is_a_conflict(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),  # below threshold -- already approved
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.post(
        f"/api/v1/orders/{order_id}/approve",
        json={"symbol": "AAPL"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 409


# --- read: list/detail, ownership -----------------------------------------------------------


def test_get_order_returns_its_own_order_with_event_history(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]

    response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["order"]["id"] == order_id
    assert isinstance(body["events"], list)


def test_get_order_rejects_another_customers_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]
    client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    other_client, _ = _authed_client(
        api_client, owner_engine, email="other-customer@trueup.example"
    )

    response = other_client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 404


def test_list_orders_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/orders")
    # 401, not 403: no session is an authentication failure, not an authorization one -- a
    # frontend that keys "session expired -> re-login" off 401 must actually see it here.
    assert response.status_code == 401
    assert response.get_json()["code"] == "unauthenticated"


def test_get_order_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/orders/{uuid.uuid4()}")
    assert response.status_code == 401
    assert response.get_json()["code"] == "unauthenticated"


# --- read: fill timeline (S3 §6 order-detail depth) ------------------------------------------


def test_get_order_includes_a_fill_timeline_in_seq_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = uuid.UUID(create_response.get_json()["id"])
    _advance_order_to_submitted(owner_engine, order_id)
    _record_fill(
        owner_engine,
        order_id,
        seq=2,
        execution_id="exec-timeline-1",
        quantity="10",
        price="101.50",
    )

    response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    events = response.get_json()["events"]
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs)  # a real fill timeline, in `seq` order

    submitted = next(e for e in events if e["event_type"] == "submitted")
    fill = next(e for e in events if e["event_type"] == "fill")
    assert submitted["quantity"] is None  # a `submitted` event carries neither
    assert submitted["price"] is None
    assert Units(fill["quantity"]) == Units("10")
    assert Price(fill["price"]) == Price("101.50")
    assert fill["execution_id"] == "exec-timeline-1"


# --- read: lot linkage (S5 FK; S3 §6 order-detail depth) -------------------------------------


def test_get_order_shows_opened_lots_for_a_buy_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    body = create_response.get_json()
    order_id = uuid.UUID(body["id"])
    customer_id = uuid.UUID(body["customer_id"])
    _advance_order_to_submitted(owner_engine, order_id)
    _record_fill(
        owner_engine, order_id, seq=2, execution_id="exec-open-1", quantity="10", price="100.00"
    )

    lot_id = uuid.uuid4()
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        session.add(
            TaxLot(
                id=lot_id,
                customer_id=customer_id,
                security_id=SECURITY_ID,
                opening_fill_execution_id="exec-open-1",
                quantity_opened=Units("10"),
                quantity_remaining=Units("10"),
                original_cost_basis=Money("1000.00"),
                adjusted_basis=Money("1000.00"),
                acquired_at=date(2026, 1, 5),
                designation=LotDesignation.UNSPECIFIED,
                designation_window_closes_at=datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    detail = response.get_json()
    assert detail["consumed_lots"] == []
    assert len(detail["opened_lots"]) == 1
    opened = detail["opened_lots"][0]
    assert opened["id"] == str(lot_id)
    assert opened["opening_fill_execution_id"] == "exec-open-1"
    assert Units(opened["quantity_opened"]) == Units("10")
    assert Money(opened["original_cost_basis"]) == Money("1000.00")


def test_get_order_shows_consumed_lots_for_a_sell_order(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    # Seed the lot a subsequent sell will consume, via a separate buy order's own fill.
    buy_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    buy_body = buy_response.get_json()
    buy_order_id = uuid.UUID(buy_body["id"])
    customer_id = uuid.UUID(buy_body["customer_id"])
    _advance_order_to_submitted(owner_engine, buy_order_id)
    _record_fill(
        owner_engine,
        buy_order_id,
        seq=2,
        execution_id="exec-source-1",
        quantity="10",
        price="100.00",
    )

    lot_id = uuid.uuid4()
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        session.add(
            TaxLot(
                id=lot_id,
                customer_id=customer_id,
                security_id=SECURITY_ID,
                opening_fill_execution_id="exec-source-1",
                quantity_opened=Units("10"),
                quantity_remaining=Units("0"),
                original_cost_basis=Money("1000.00"),
                adjusted_basis=Money("1000.00"),
                acquired_at=date(2026, 1, 5),
                designation=LotDesignation.UNSPECIFIED,
                designation_window_closes_at=datetime(2026, 1, 5, 23, 59, tzinfo=UTC),
            )
        )
        session.commit()
    finally:
        session.close()

    sell_response = client.post(
        "/api/v1/orders",
        json=_create_payload(side="sell"),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    sell_order_id = uuid.UUID(sell_response.get_json()["id"])
    _advance_order_to_submitted(owner_engine, sell_order_id)
    _record_fill(
        owner_engine,
        sell_order_id,
        seq=2,
        execution_id="exec-close-1",
        quantity="10",
        price="105.00",
    )

    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        session.add(
            LotConsumption(
                closing_fill_execution_id="exec-close-1",
                tax_lot_id=lot_id,
                quantity_consumed=Units("10"),
                realized_gain_loss=Money("50.00"),
                is_provisional=False,
                sale_date=date(2026, 1, 10),
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.get(f"/api/v1/orders/{sell_order_id}")

    assert response.status_code == 200
    detail = response.get_json()
    assert detail["opened_lots"] == []
    assert len(detail["consumed_lots"]) == 1
    consumed = detail["consumed_lots"][0]
    assert consumed["tax_lot_id"] == str(lot_id)
    assert consumed["closing_fill_execution_id"] == "exec-close-1"
    assert Units(consumed["quantity_consumed"]) == Units("10")
    assert Money(consumed["realized_gain_loss"]) == Money("50.00")


# --- create: customer-safe ineligibility reasons (never the raw internal reason) -------------


@pytest.mark.parametrize(
    ("kyc_status", "account_status", "expected_code"),
    [
        (KycStatus.pending, AccountApprovalStatus.approved, "kyc_verification_pending"),
        (KycStatus.rejected, AccountApprovalStatus.approved, "kyc_verification_rejected"),
        (KycStatus.approved, AccountApprovalStatus.pending, "account_approval_pending"),
        (KycStatus.approved, AccountApprovalStatus.rejected, "account_approval_rejected"),
    ],
)
def test_create_order_maps_each_ineligibility_reason_to_a_distinct_safe_code(
    api_client: FlaskClient,
    owner_engine: Engine,
    kyc_status: KycStatus,
    account_status: AccountApprovalStatus,
    expected_code: str,
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        customer = session.query(Customer).filter_by(email=CUSTOMER_EMAIL).one()
        customer.kyc_status = kyc_status
        customer.account_approval_status = account_status
        session.commit()
    finally:
        session.close()

    response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 403
    assert response.get_json()["code"] == expected_code


def test_ineligibility_code_maps_unmapped_reasons_to_the_generic_safe_code() -> None:
    """`customer_not_found` is a defensive-only path -- an authenticated session already implies
    flask-login's own loader resolved a live `Customer` row, so a real HTTP request can never
    reach `_require_eligible_customer` with that reason. Exercised directly at the mapping-
    function level rather than through the Flask test client for exactly that reason; also covers
    any future reason this allowlist hasn't been extended for yet, which must degrade the same way
    rather than leak the raw internal string."""
    assert (
        orders_controller._ineligibility_code(CustomerNotEligibleError("customer_not_found"))
        == "customer_not_eligible"
    )
    assert (
        orders_controller._ineligibility_code(CustomerNotEligibleError("some_future_gate"))
        == "customer_not_eligible"
    )


# --- cancel (ADR 25): request only, never a local state mutation -----------------------------


def _create_and_submit_order(
    client: FlaskClient,
    owner_engine: Engine,
    csrf_token: str,
    *,
    broker_order_id: str = "fake-broker-order-1",
) -> uuid.UUID:
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = uuid.UUID(create_response.get_json()["id"])
    _advance_order_to_submitted(owner_engine, order_id, broker_order_id=broker_order_id)
    return order_id


@pytest.fixture
def _fake_broker(monkeypatch: pytest.MonkeyPatch) -> FakeBrokerAdapter:
    broker = FakeBrokerAdapter()
    monkeypatch.setattr(orders_controller, "_build_broker_port", lambda: broker)
    return broker


def test_cancel_requests_the_broker_and_leaves_status_unchanged(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    order_id = _create_and_submit_order(
        client, owner_engine, csrf_token, broker_order_id="broker-order-A"
    )

    response = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "submitted"  # unchanged -- only the websocket confirmation moves it
    assert _fake_broker.cancel_requests == ["broker-order-A"]


def test_cancel_is_idempotent_while_the_order_is_still_cancellable(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    order_id = _create_and_submit_order(
        client, owner_engine, csrf_token, broker_order_id="broker-order-B"
    )

    first = client.post(f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token})
    second = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token}
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert _fake_broker.cancel_requests == ["broker-order-B", "broker-order-B"]


def test_cancel_a_pre_submission_order_is_a_conflict(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(),
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = create_response.get_json()["id"]  # still `approved` -- never submitted

    response = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 409
    assert _fake_broker.cancel_requests == []


def test_cancel_an_already_filled_order_is_a_conflict(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    order_id = _create_and_submit_order(client, owner_engine, csrf_token)
    _record_fill(
        owner_engine, order_id, seq=2, execution_id="exec-filled-1", quantity="10", price="100.00"
    )

    response = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 409
    assert _fake_broker.cancel_requests == []


def test_cancel_another_customers_order_is_not_found(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)
    order_id = _create_and_submit_order(client, owner_engine, csrf_token)
    client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    other_client, other_csrf = _authed_client(
        api_client, owner_engine, email="other-canceler@trueup.example"
    )

    response = other_client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": other_csrf}
    )

    assert response.status_code == 404
    assert _fake_broker.cancel_requests == []


def test_cancel_a_nonexistent_order_returns_not_found(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    client, csrf_token = _authed_client(api_client, owner_engine)

    response = client.post(
        f"/api/v1/orders/{uuid.uuid4()}/cancel", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 404


def test_cancel_with_no_session_is_rejected(api_client: FlaskClient) -> None:
    response = api_client.post(f"/api/v1/orders/{uuid.uuid4()}/cancel")
    # 400, not 401: CSRFProtect rejects first with no token at all, matching create/approve's own
    # precedent (`test_create_order_with_no_session_is_rejected`) for every POST route here.
    assert response.status_code == 400


def test_cancel_releases_no_hold_before_the_websocket_confirms_it(
    api_client: FlaskClient, owner_engine: Engine, _fake_broker: FakeBrokerAdapter
) -> None:
    """The hold is already `released` (`approved_and_submitted`) by the time an order is
    cancellable; `request_cancel` must not touch it, and the broker-confirmed `canceled` event
    landing afterward must not touch it either (S3 §4/ADR 25)."""
    client, csrf_token = _authed_client(api_client, owner_engine)
    create_response = client.post(
        "/api/v1/orders",
        json=_create_payload(quantity="1000", reference_price="100.00"),  # above threshold
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )
    order_id = uuid.UUID(create_response.get_json()["id"])
    client.post(
        f"/api/v1/orders/{order_id}/approve", headers={"X-CSRFToken": csrf_token}
    )
    _advance_order_to_submitted(owner_engine, order_id)

    def _hold_snapshot() -> tuple[str, str | None]:
        session = Session(bind=owner_engine, expire_on_commit=False)
        try:
            hold = session.query(ApprovalHold).filter_by(order_id=order_id).one()
            return hold.status.value, (
                hold.release_reason.value if hold.release_reason is not None else None
            )
        finally:
            session.close()

    before = _hold_snapshot()
    assert before == ("released", "approved_and_submitted")

    response = client.post(
        f"/api/v1/orders/{order_id}/cancel", headers={"X-CSRFToken": csrf_token}
    )
    assert response.status_code == 200
    assert _hold_snapshot() == before  # request_cancel touched neither status nor reason

    session = Session(bind=owner_engine, expire_on_commit=False)
    try:
        order = session.get(Order, order_id)
        assert order is not None
        session.add(
            OrderEvent(
                order_id=order_id,
                seq=3,
                event_type=OrderEventType.CANCELED,
                payload={},
            )
        )
        order.status = OrderStatus.CANCELED
        session.commit()
    finally:
        session.close()

    assert _hold_snapshot() == before  # still the original release, not re-touched by "canceled"
