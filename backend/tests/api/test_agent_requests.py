"""`app/controllers/admin/agent_requests.py` (S13 §5) via the Flask test client: the human
approval queue for MCP write-tool proposals, including all three execution mappings.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pyotp
import pytest
from flask.testing import FlaskClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.models.identity.staff import Staff, StaffRole
from app.models.ops.admin_audit_log import AdminAuditLog
from app.models.ops.agent_action_request import (
    AgentActionRequest,
    AgentActionStatus,
    AgentActionType,
)
from app.models.rebalance.customer_model_assignment import CustomerModelAssignment
from app.models.rebalance.model_portfolio import ModelPortfolio
from app.models.reconciliation.reconciliation_break import (
    ReconciliationBreak,
    ReconciliationBreakStatus,
    ReconciliationBreakType,
)
from app.services.identity.auth import hash_password

STAFF_EMAIL = "agent-requests-adviser@trueup.example"
STAFF_PASSWORD = "another-strong-password"

_TABLES = [
    # Customer/Staff are owned by tests/api/conftest.py's session-scoped fixture, not here.
    AgentActionRequest.__table__,
    AdminAuditLog.__table__,
    ReconciliationBreak.__table__,
    ModelPortfolio.__table__,
    CustomerModelAssignment.__table__,
]


@pytest.fixture(autouse=True)
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


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


def _staff_login_with_mfa(client: FlaskClient) -> str:
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
    csrf_token: str = verify.get_json()["csrf_token"]
    return csrf_token


def _insert_customer(owner_engine: Engine) -> uuid.UUID:
    with Session(bind=owner_engine, expire_on_commit=False) as session:
        customer = Customer(
            email=f"{uuid.uuid4()}@trueup.test",
            password_hash="hash",
            kyc_status=KycStatus.rejected,
            account_approval_status=AccountApprovalStatus.pending,
        )
        session.add(customer)
        session.commit()
        return customer.id


def _insert_break(owner_engine: Engine) -> uuid.UUID:
    with Session(bind=owner_engine, expire_on_commit=False) as session:
        break_row = ReconciliationBreak(
            break_type=ReconciliationBreakType.CASH_MISMATCH,
            customer_id=uuid.uuid4(),
            opened_at=datetime.now(UTC),
            status=ReconciliationBreakStatus.OPEN,
            import_batch_id=uuid.uuid4(),
        )
        session.add(break_row)
        session.commit()
        return break_row.id


def _insert_request(
    owner_engine: Engine,
    *,
    action: AgentActionType,
    arguments: dict[str, object],
    status: AgentActionStatus = AgentActionStatus.PENDING,
) -> uuid.UUID:
    """A non-`pending` row must also carry `reviewed_by`/`reviewed_at` (S13 §3.1 CHECK
    constraint)."""
    with Session(bind=owner_engine, expire_on_commit=False) as session:
        row = AgentActionRequest(
            action=action,
            arguments=arguments,
            requesting_agent="adviser@trueup.test (test token)",
            justification="test justification",
            status=status,
            reviewed_by=uuid.uuid4() if status != AgentActionStatus.PENDING else None,
            reviewed_at=datetime.now(UTC) if status != AgentActionStatus.PENDING else None,
        )
        session.add(row)
        session.commit()
        return row.id


# --- authn/authz ---------------------------------------------------------------------------------


def test_list_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.get("/api/v1/admin/agent-requests")

    assert response.status_code == 401


def test_approve_requires_authentication(api_client: FlaskClient) -> None:
    response = api_client.post(f"/api/v1/admin/agent-requests/{uuid.uuid4()}/approve")

    assert response.status_code == 400  # CSRFProtect rejects an unauthenticated POST first.


def test_a_customer_session_gets_403_not_404(api_client: FlaskClient) -> None:
    register_response = api_client.post(
        "/api/v1/auth/register",
        json={"email": "customer@trueup.example", "password": "correct-horse-battery"},
    )
    assert register_response.status_code == 201
    login_response = api_client.post(
        "/api/v1/auth/login",
        json={"email": "customer@trueup.example", "password": "correct-horse-battery"},
    )
    csrf_token = login_response.get_json()["csrf_token"]

    response = api_client.get(
        "/api/v1/admin/agent-requests", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 403


# --- list/get --------------------------------------------------------------------------------


def test_list_defaults_to_pending_and_is_oldest_first(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    first = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "first"},
    )
    second = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "second"},
    )

    response = api_client.get(
        "/api/v1/admin/agent-requests", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 200
    body = response.get_json()
    ids = [row["id"] for row in body["requests"]]
    assert ids == [str(first), str(second)]


def test_get_one_returns_404_for_unknown_id(
    api_client: FlaskClient, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.get(
        f"/api/v1/admin/agent-requests/{uuid.uuid4()}", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 404


# --- approve: resolve_break execution mapping ---------------------------------------------------


def test_approving_a_resolve_break_request_actually_resolves_the_break(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    break_id = _insert_break(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.RESOLVE_BREAK,
        arguments={"break_id": str(break_id), "resolution_note": "confirmed with custodian"},
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/approve",
        json={"review_note": "approved"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "executed"
    assert body["executed_at"] is not None

    with Session(bind=owner_engine, expire_on_commit=False) as session:
        break_row = session.get(ReconciliationBreak, break_id)
        assert break_row is not None
        assert break_row.status is ReconciliationBreakStatus.RESOLVED
        assert break_row.resolution_note == "confirmed with custodian"


def test_approving_a_resolve_break_request_for_an_already_resolved_break_records_execution_failed(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    break_id = _insert_break(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.RESOLVE_BREAK,
        arguments={"break_id": str(break_id), "resolution_note": "confirmed"},
    )

    # Someone else resolves the break out-of-band, between proposal and approval (S13 §6).
    with Session(bind=owner_engine, expire_on_commit=False) as session:
        break_row = session.get(ReconciliationBreak, break_id)
        assert break_row is not None
        break_row.status = ReconciliationBreakStatus.RESOLVED
        break_row.resolved_by = uuid.uuid4()
        break_row.resolved_at = datetime.now(UTC)
        session.commit()

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/approve",
        json={"review_note": "approved"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "execution_failed"
    assert body["execution_error"] is not None
    assert body["executed_at"] is None


# --- approve: kyc_override execution mapping -----------------------------------------------------


def test_approving_a_kyc_override_request_actually_resets_kyc_status(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "confirmed manually"},
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/approve",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "executed"

    with Session(bind=owner_engine, expire_on_commit=False) as session:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        assert customer.kyc_status is KycStatus.pending


# --- approve: rebalance execution mapping (execution-failure path) --------------------------------


def test_approving_a_rebalance_request_with_no_assigned_model_records_execution_failed(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    request_id = _insert_request(
        owner_engine, action=AgentActionType.REBALANCE, arguments={"customer_id": str(customer_id)}
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/approve",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "execution_failed"
    assert body["execution_error"] is not None


# --- approve: transition/validation errors -------------------------------------------------------


def test_approve_returns_404_for_unknown_id(api_client: FlaskClient, staff_member: Staff) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{uuid.uuid4()}/approve",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 404


def test_approve_a_non_pending_request_returns_409(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "x"},
        status=AgentActionStatus.REJECTED,
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/approve",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 409


# --- reject ----------------------------------------------------------------------------------


def test_reject_requires_a_non_empty_review_note(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "x"},
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/reject",
        json={},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422


def test_reject_never_touches_customer_state(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)
    customer_id = _insert_customer(owner_engine)
    request_id = _insert_request(
        owner_engine,
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(customer_id), "reason": "x"},
    )

    response = api_client.post(
        f"/api/v1/admin/agent-requests/{request_id}/reject",
        json={"review_note": "not warranted"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "rejected"

    with Session(bind=owner_engine, expire_on_commit=False) as session:
        customer = session.get(Customer, customer_id)
        assert customer is not None
        assert customer.kyc_status is KycStatus.rejected  # unchanged


# --- throttling -------------------------------------------------------------------------------


def test_approve_is_throttled(
    api_client: FlaskClient, owner_engine: Engine, staff_member: Staff
) -> None:
    csrf_token = _staff_login_with_mfa(api_client)

    last_response = None
    for _ in range(31):
        last_response = api_client.post(
            f"/api/v1/admin/agent-requests/{uuid.uuid4()}/approve",
            json={},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
