"""`KycService` (S2 §4/§5.1) — pure unit tests against real fakes, no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.models.identity.customer import Customer, KycStatus
from app.models.identity.kyc_session import KycSession, KycSessionStatus, SqlKycSessionRepository
from app.services.identity.kyc_service import (
    CustomerNotFoundError,
    KycLockedError,
    KycPortNotConfiguredError,
    KycService,
)

MAX_ATTEMPTS = 3


class _FakeKycSessions:
    def __init__(self) -> None:
        self.rows: dict[str, KycSession] = {}

    def add(self, row: KycSession) -> None:
        self.rows[row.provider_session_id] = row

    def get_by_provider_session_id(self, provider_session_id: str) -> KycSession | None:
        return self.rows.get(provider_session_id)

    def latest_for_customer(self, customer_id: uuid.UUID) -> KycSession | None:
        candidates = [row for row in self.rows.values() if row.customer_id == customer_id]
        if not candidates:
            return None
        return max(candidates, key=lambda row: row.attempt_number)

    def resolve(
        self, session_row: KycSession, *, status: KycSessionStatus, resolved_at: datetime
    ) -> None:
        SqlKycSessionRepository.resolve(session_row, status=status, resolved_at=resolved_at)


class _FakeCustomers:
    def __init__(self, customers: dict[uuid.UUID, Customer]) -> None:
        self._customers = customers

    def get_by_id(self, customer_id: uuid.UUID) -> Customer | None:
        return self._customers.get(customer_id)


class _FakeUow:
    def __init__(self, customer: Customer) -> None:
        self.kyc_sessions = _FakeKycSessions()
        self.customers = _FakeCustomers({customer.id: customer})


def _customer() -> Customer:
    return Customer(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=KycStatus.pending,
    )


def _service(uow: _FakeUow, port: FakeKycAdapter) -> KycService:
    return KycService(uow, kyc_port=port, max_attempts=MAX_ATTEMPTS, now=lambda: datetime.now(UTC))  # type: ignore[arg-type]


def test_start_verification_opens_attempt_one_then_attempt_two() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())

    service.start_verification(customer.id)
    service.start_verification(customer.id)

    attempts = sorted(row.attempt_number for row in uow.kyc_sessions.rows.values())
    assert attempts == [1, 2]


def test_verified_verdict_approves_the_session_and_the_customer() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)

    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="verified"
    )

    session_row = uow.kyc_sessions.get_by_provider_session_id(handle.provider_session_id)
    assert session_row is not None
    assert session_row.status is KycSessionStatus.APPROVED
    assert customer.kyc_status is KycStatus.approved


def test_canceled_verdict_rejects_the_session_and_the_customer() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)

    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="canceled"
    )

    assert customer.kyc_status is KycStatus.rejected


def test_processing_verdict_stays_pending_and_never_touches_the_customer() -> None:
    """ADR 9: a session stuck in `processing` must never be misreported as `rejected`."""
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)

    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="processing"
    )

    session_row = uow.kyc_sessions.get_by_provider_session_id(handle.provider_session_id)
    assert session_row is not None
    assert session_row.status is KycSessionStatus.PENDING
    assert customer.kyc_status is KycStatus.pending


def test_requires_input_past_the_attempt_cap_rejects() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)
    session_row = uow.kyc_sessions.get_by_provider_session_id(handle.provider_session_id)
    assert session_row is not None
    session_row.attempt_number = MAX_ATTEMPTS

    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="requires_input"
    )

    assert customer.kyc_status is KycStatus.rejected


def test_unknown_provider_session_id_raises() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())

    with pytest.raises(CustomerNotFoundError):
        service.apply_verification_verdict(
            provider_session_id="vs_unknown", stripe_status="verified"
        )


def test_start_verification_is_blocked_once_locked_rejected() -> None:
    """S2 §9/S8 §6 case 3: exhausted attempts lock `kyc_status`; only admin override reopens it."""
    customer = _customer()
    uow = _FakeUow(customer)
    port = FakeKycAdapter()
    service = _service(uow, port)
    handle = service.start_verification(customer.id)
    session_row = uow.kyc_sessions.get_by_provider_session_id(handle.provider_session_id)
    assert session_row is not None
    session_row.attempt_number = MAX_ATTEMPTS
    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="requires_input"
    )
    assert customer.kyc_status is KycStatus.rejected

    with pytest.raises(KycLockedError):
        service.start_verification(customer.id)


def test_sync_latest_verification_applies_a_live_verified_status_with_no_webhook() -> None:
    """The safety net: a customer whose verdict webhook never arrives (e.g. localhost in local
    dev) still gets approved once something asks the provider directly."""
    customer = _customer()
    uow = _FakeUow(customer)
    port = FakeKycAdapter()
    service = _service(uow, port)
    handle = service.start_verification(customer.id)
    port.retrieved_statuses[handle.provider_session_id] = "verified"

    result = service.sync_latest_verification(customer.id)

    assert result == customer.id
    assert customer.kyc_status is KycStatus.approved
    session_row = uow.kyc_sessions.get_by_provider_session_id(handle.provider_session_id)
    assert session_row is not None
    assert session_row.status is KycSessionStatus.APPROVED


def test_sync_latest_verification_no_ops_when_still_pending_at_the_provider() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    port = FakeKycAdapter()
    service = _service(uow, port)
    handle = service.start_verification(customer.id)
    port.retrieved_statuses[handle.provider_session_id] = "processing"

    result = service.sync_latest_verification(customer.id)

    assert result is None
    assert customer.kyc_status is KycStatus.pending


def test_sync_latest_verification_no_ops_when_already_terminal_and_never_calls_the_port() -> None:
    """Once resolved, syncing again must not re-poll the provider at all."""
    customer = _customer()
    uow = _FakeUow(customer)
    port = FakeKycAdapter()
    service = _service(uow, port)
    handle = service.start_verification(customer.id)
    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="verified"
    )
    # Would flip the customer to rejected if (wrongly) called again.
    port.retrieved_statuses[handle.provider_session_id] = "canceled"

    result = service.sync_latest_verification(customer.id)

    assert result is None
    assert customer.kyc_status is KycStatus.approved


def test_sync_latest_verification_no_ops_when_no_session_exists_yet() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())

    assert service.sync_latest_verification(customer.id) is None


def test_sync_latest_verification_requires_a_configured_port() -> None:
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)
    assert handle is not None
    unconfigured = KycService(uow, kyc_port=None, max_attempts=MAX_ATTEMPTS)  # type: ignore[arg-type]

    with pytest.raises(KycPortNotConfiguredError):
        unconfigured.sync_latest_verification(customer.id)


def test_start_verification_allows_a_retry_below_the_attempt_cap() -> None:
    """A canceled attempt sets `kyc_status = rejected` (ADR 9) but must not lock out a retry."""
    customer = _customer()
    uow = _FakeUow(customer)
    service = _service(uow, FakeKycAdapter())
    handle = service.start_verification(customer.id)
    service.apply_verification_verdict(
        provider_session_id=handle.provider_session_id, stripe_status="canceled"
    )
    assert customer.kyc_status is KycStatus.rejected

    service.start_verification(customer.id)

    attempts = sorted(row.attempt_number for row in uow.kyc_sessions.rows.values())
    assert attempts == [1, 2]
