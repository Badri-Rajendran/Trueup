"""`KycService` (S2 §4/§5.1) — pure unit tests against real fakes, no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.integrations.fake.fake_kyc import FakeKycAdapter
from app.models.identity.customer import Customer, KycStatus
from app.models.identity.kyc_session import KycSession, KycSessionStatus, SqlKycSessionRepository
from app.services.identity.kyc_service import CustomerNotFoundError, KycLockedError, KycService

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
    """ADR 9's explicit warning: a session stuck in `processing` must never be misreported as
    `rejected` by a naive "not yet verified = rejected" simplification."""
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
    """S2 §9/S8 §6 case 3: a customer whose `kyc_status` locked to `rejected` after exhausting
    `KYC_MAX_ATTEMPTS` cannot start a fresh attempt -- only the admin override (S8 §4 row 5) may
    reopen it."""
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


def test_start_verification_allows_a_retry_below_the_attempt_cap() -> None:
    """A single canceled attempt also sets `kyc_status = rejected` (ADR 9), but well below the
    attempt cap this must not lock out a normal resubmission -- only "exhausted attempts" does
    (S8 §6 case 3's own distinction)."""
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
