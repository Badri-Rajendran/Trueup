"""`POST /api/v1/funding/{bank-links,deposits,withdrawals}` (S2 §6) via the Flask test client:
happy path, validation, authn/authz/ownership, throttling, idempotency (S0 §8, NFR-14).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, select, text

from app.core.money import Money
from app.core.uow import SessionRole
from app.integrations.fake.fake_bank import FakeBankAdapter
from app.models.identity.bank_link import BankLink
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.ledger.account import Account, AccountRole
from app.models.ledger.customer_cash_lock import CustomerCashLock
from app.models.ledger.journal_entry import JournalEntry
from app.models.ledger.posting import Posting
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ops.idempotency_key import IdempotencyKey
from app.models.ops.inbound_event import InboundEvent
from app.models.orders.approval_hold import ApprovalHold
from app.models.orders.order import Order
from app.services.identity.deposit_service import DepositService
from app.services.identity.funding_uow import FundingUnitOfWork

CUSTOMER_EMAIL = "funding-customer@trueup.example"
CUSTOMER_PASSWORD = "correct-horse-battery"
OTHER_EMAIL = "funding-other@trueup.example"

_TABLES = [
    InboundEvent.__table__,
    BankLink.__table__,
    Account.__table__,
    JournalEntry.__table__,
    Posting.__table__,
    SettlementObligation.__table__,
    CustomerCashLock.__table__,
    IdempotencyKey.__table__,
    # Withdrawal checks real order holds (OrderHoldsProvider); these tables must exist.
    Order.__table__,
    ApprovalHold.__table__,
]


@pytest.fixture(autouse=True)
def _funding_tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture(autouse=True)
def _fake_bank_port(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.controllers.api.funding as funding_controller

    monkeypatch.setattr(funding_controller, "_plaid_adapter", lambda: FakeBankAdapter())


def _register_and_login(
    client: FlaskClient, *, email: str = CUSTOMER_EMAIL, password: str = CUSTOMER_PASSWORD
) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _link_bank(client: FlaskClient, *, customer_id: str, csrf_token: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/funding/bank-links",
        json={"customer_id": customer_id, "plaid_public_token": "public-fake-token"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert response.status_code == 201
    return response.get_json()


def _approve_customer(db_committing, customer_id: str) -> None:
    customer = db_committing.execute(
        select(Customer).where(Customer.id == uuid.UUID(customer_id))
    ).scalar_one()
    customer.kyc_status = KycStatus.approved
    customer.account_approval_status = AccountApprovalStatus.approved
    db_committing.add(Account.create(AccountRole.CASH, customer_id=customer.id))
    db_committing.add(Account.create(AccountRole.CUSTOMER_EQUITY, customer_id=customer.id))
    db_committing.add(CustomerCashLock(customer_id=customer.id))
    db_committing.commit()


# --- POST /bank-links ----------------------------------------------------------------------


def test_create_bank_link_happy_path(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    body = _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)

    assert body["status"] == "active"
    assert "plaid_access_token" not in body


def test_create_bank_link_rejects_missing_fields(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/funding/bank-links", json={}, headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_create_bank_link_rejects_another_customers_id(api_client: FlaskClient) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/funding/bank-links",
        json={"customer_id": other_id, "plaid_public_token": "public-fake-token"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 403


def test_create_bank_link_is_throttled(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            "/api/v1/funding/bank-links",
            json={"customer_id": customer_id, "plaid_public_token": "public-fake-token"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- POST /deposits ------------------------------------------------------------------------


def test_create_deposit_happy_path(api_client: FlaskClient, db_committing) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["journal_entry_id"]
    assert body["settlement_obligation_id"]


def test_create_deposit_requires_idempotency_key(api_client: FlaskClient, db_committing) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


def test_create_deposit_replays_the_same_response_for_a_repeated_key(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)
    key = str(uuid.uuid4())
    payload = {"customer_id": customer_id, "amount": "500.00"}

    first = api_client.post(
        "/api/v1/funding/deposits",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    second = api_client.post(
        "/api/v1/funding/deposits",
        json=payload,
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.get_json() == second.get_json()

    entries = db_committing.execute(select(JournalEntry)).scalars().all()
    assert len(entries) == 1


def test_create_deposit_rejects_a_reused_key_with_a_different_body(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)
    key = str(uuid.uuid4())

    first = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )
    assert first.status_code == 201

    second = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "999.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": key},
    )

    assert second.status_code == 409


def test_create_deposit_rejects_when_kyc_is_not_approved(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "kyc_status_pending"


def test_create_deposit_rejects_over_the_per_transaction_cap(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "25000.01"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "deposit_cap_exceeded_per_transaction"


def test_create_deposit_is_throttled(api_client: FlaskClient, db_committing) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    last_response = None
    for _ in range(11):
        last_response = api_client.post(
            "/api/v1/funding/deposits",
            json={"customer_id": customer_id, "amount": "1.00"},
            headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- POST /withdrawals ---------------------------------------------------------------------


def test_create_withdrawal_rejects_insufficient_withdrawable_cash(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.post(
        "/api/v1/funding/withdrawals",
        json={"customer_id": customer_id, "amount": "100.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "insufficient_withdrawable_cash"


def test_create_withdrawal_rejects_another_customers_id(api_client: FlaskClient) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/funding/withdrawals",
        json={"customer_id": other_id, "amount": "1.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    assert response.status_code == 403


def test_create_withdrawal_requires_idempotency_key(api_client: FlaskClient) -> None:
    customer_id, csrf_token = _register_and_login(api_client)

    response = api_client.post(
        "/api/v1/funding/withdrawals",
        json={"customer_id": customer_id, "amount": "1.00"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422
    assert response.get_json()["code"] == "validation_failed"


# --- helpers for states with no HTTP path ---------------------------------------------------


def _confirm_obligation(customer_id: str, *, journal_entry_id: str) -> None:
    """Drives `settlement_obligations.confirm(...)` directly -- nothing in `app/` calls it over
    HTTP today (an ACH confirmation arrives out-of-band from the custodian in production)."""
    with FundingUnitOfWork(
        customer_id=uuid.UUID(customer_id), role=SessionRole.CUSTOMER
    ) as uow:
        obligations = uow.settlement_obligations.list_for_customer(uuid.UUID(customer_id))
        obligation = next(o for o in obligations if str(o.journal_entry_id) == journal_entry_id)
        uow.settlement_obligations.confirm(obligation, confirmed_at=datetime.now(UTC))
        uow.commit()


def _bounce_deposit(customer_id: str, *, settlement_obligation_id: str) -> None:
    """Drives `DepositService.apply_ach_return(...)` directly -- same rationale as
    `_confirm_obligation`: the ACH return is a custodian-initiated event with no HTTP entry
    point in this codebase (mirrors `test_deposit_service.py`'s own fixture pattern)."""
    with FundingUnitOfWork(
        customer_id=uuid.UUID(customer_id), role=SessionRole.CUSTOMER
    ) as uow:
        DepositService(
            uow,
            deposit_cap_per_transaction=Money("25000.00"),
            deposit_cap_per_day=Money("50000.00"),
        ).apply_ach_return(uuid.UUID(settlement_obligation_id))
        uow.commit()


# --- GET /cash-summary -----------------------------------------------------------------------


def test_get_cash_summary_reports_the_caps_and_zero_usage_for_a_new_customer(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.get(f"/api/v1/funding/cash-summary?customer_id={customer_id}")

    assert response.status_code == 200
    body = response.get_json()
    assert body["outstanding_receivable"] == "0.0000"
    assert body["deposit_cap_per_transaction"] == "25000.0000"
    assert body["deposit_cap_per_day"] == "50000.0000"
    assert body["deposited_today"] == "0.0000"


def test_get_cash_summary_counts_todays_deposit_in_deposited_today(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    before = api_client.get(f"/api/v1/funding/cash-summary?customer_id={customer_id}").get_json()

    api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    after = api_client.get(f"/api/v1/funding/cash-summary?customer_id={customer_id}").get_json()

    assert after["deposited_today"] == "500.0000"
    assert Decimal(after["investable"]) == Decimal(before["investable"]) + Decimal("500.0000")
    assert after["withdrawable"] == before["withdrawable"]


def test_get_cash_summary_reports_the_receivable_balance_after_an_ach_return(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    deposit = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()

    _bounce_deposit(customer_id, settlement_obligation_id=deposit["settlement_obligation_id"])

    response = api_client.get(f"/api/v1/funding/cash-summary?customer_id={customer_id}")

    assert response.status_code == 200
    assert response.get_json()["outstanding_receivable"] == "500.0000"


def test_get_cash_summary_is_throttled(api_client: FlaskClient, db_committing) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    last_response = None
    for _ in range(61):
        last_response = api_client.get(f"/api/v1/funding/cash-summary?customer_id={customer_id}")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /funding/history ----------------------------------------------------------------------


def test_get_funding_history_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get(f"/api/v1/funding/history?customer_id={uuid.uuid4()}")

    assert response.status_code == 401


def test_get_funding_history_is_empty_for_a_new_customer(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    assert response.status_code == 200
    assert response.get_json() == {"entries": []}


def test_get_funding_history_shows_a_new_deposit_as_pending_with_its_expected_settlement_date(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    deposit = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    assert response.status_code == 200
    entries = response.get_json()["entries"]
    assert len(entries) == 1
    entry = entries[0]
    assert entry["journal_entry_id"] == deposit["journal_entry_id"]
    assert entry["entry_type"] == "deposit"
    assert entry["amount"] == "500.0000"
    assert entry["settlement_status"] == "pending"
    assert entry["expected_settlement_date"] == deposit["expected_settlement_date"]
    assert entry["failure_reason"] is None


def test_get_funding_history_emits_one_row_per_deposit_not_one_per_posting(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    assert len(response.get_json()["entries"]) == 1


def test_get_funding_history_shows_a_confirmed_deposit_as_confirmed(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    deposit = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()

    _confirm_obligation(customer_id, journal_entry_id=deposit["journal_entry_id"])

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    entries = response.get_json()["entries"]
    assert len(entries) == 1
    assert entries[0]["settlement_status"] == "confirmed"


def test_get_funding_history_shows_a_returned_deposit_as_failed_with_its_reason(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    deposit = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()

    _bounce_deposit(customer_id, settlement_obligation_id=deposit["settlement_obligation_id"])

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    entries = response.get_json()["entries"]
    assert len(entries) == 1
    assert entries[0]["settlement_status"] == "failed"
    assert entries[0]["failure_reason"] == "ach_return"


def test_get_funding_history_reports_a_withdrawal_with_no_settlement_status(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)
    deposit = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "500.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()
    _confirm_obligation(customer_id, journal_entry_id=deposit["journal_entry_id"])

    api_client.post(
        "/api/v1/funding/withdrawals",
        json={"customer_id": customer_id, "amount": "100.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    )

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    entries = response.get_json()["entries"]
    withdrawal = next(e for e in entries if e["entry_type"] == "withdrawal")
    assert withdrawal["amount"] == "-100.0000"
    assert withdrawal["settlement_status"] is None
    assert withdrawal["expected_settlement_date"] is None
    assert withdrawal["failure_reason"] is None


def test_get_funding_history_orders_newest_first(
    api_client: FlaskClient, db_committing
) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    first = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "100.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()
    second = api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": customer_id, "amount": "200.00"},
        headers={"X-CSRFToken": csrf_token, "Idempotency-Key": str(uuid.uuid4())},
    ).get_json()

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    entries = response.get_json()["entries"]
    ids = [e["journal_entry_id"] for e in entries]
    assert ids.index(second["journal_entry_id"]) < ids.index(first["journal_entry_id"])


def test_get_funding_history_excludes_another_customers_activity(
    api_client: FlaskClient, db_committing
) -> None:
    other_id, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    _link_bank(api_client, customer_id=other_id, csrf_token=other_csrf)
    _approve_customer(db_committing, other_id)
    api_client.post(
        "/api/v1/funding/deposits",
        json={"customer_id": other_id, "amount": "500.00"},
        headers={"X-CSRFToken": other_csrf, "Idempotency-Key": str(uuid.uuid4())},
    )
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": other_csrf})

    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    assert response.get_json() == {"entries": []}


def test_get_funding_history_is_throttled(api_client: FlaskClient, db_committing) -> None:
    customer_id, csrf_token = _register_and_login(api_client)
    _link_bank(api_client, customer_id=customer_id, csrf_token=csrf_token)
    _approve_customer(db_committing, customer_id)

    last_response = None
    for _ in range(61):
        last_response = api_client.get(f"/api/v1/funding/history?customer_id={customer_id}")

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
