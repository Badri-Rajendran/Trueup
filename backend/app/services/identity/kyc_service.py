"""Starts Stripe Identity verification sessions and applies the provider's verdict (S2 §4, ADR 9)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.models.identity.customer import KycStatus
from app.models.identity.kyc_session import KycSession, KycSessionStatus

if TYPE_CHECKING:
    import uuid
    from collections.abc import Callable

    from app.integrations.ports import KycPort, KycSessionHandle
    from app.services.identity.uow import IdentityUnitOfWork


class CustomerNotFoundError(RuntimeError):
    """Raised when a webhook verdict names a `kyc_session`/`customer` that cannot be found."""


def map_verification_session_status(
    stripe_status: str, *, attempt_number: int, max_attempts: int
) -> KycSessionStatus:
    """ADR 9's status mapping: verified→approved, canceled→rejected, else pending (rejected past cap)."""
    if stripe_status == "verified":
        return KycSessionStatus.APPROVED
    if stripe_status == "canceled":
        return KycSessionStatus.REJECTED
    if stripe_status in ("requires_input", "processing"):
        if stripe_status == "requires_input" and attempt_number >= max_attempts:
            return KycSessionStatus.REJECTED
        return KycSessionStatus.PENDING
    raise ValueError(f"unrecognized Stripe Identity verification_session status: {stripe_status!r}")


class KycPortNotConfiguredError(RuntimeError):
    """Raised when `start_verification` is called on a `KycService` built without a `KycPort`."""


class KycLockedError(RuntimeError):
    """`kyc_status` locked to `rejected` after exhausting `KYC_MAX_ATTEMPTS` (S2 §3.2/§9);
    only an admin override (S8 §4 row 5) can reopen it."""


class KycService:
    def __init__(
        self,
        uow: IdentityUnitOfWork,
        *,
        kyc_port: KycPort | None = None,
        max_attempts: int,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._kyc_port = kyc_port
        self._max_attempts = max_attempts
        self._now = now

    def start_verification(self, customer_id: uuid.UUID) -> KycSessionHandle:
        """S2 §5.1/§6: `POST /identity/kyc-sessions`. Blocked outright if locked-`rejected`."""
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"no customer found for id={customer_id!r}")

        latest = self._uow.kyc_sessions.latest_for_customer(customer_id)
        if (
            customer.kyc_status is KycStatus.rejected
            and latest is not None
            and latest.attempt_number >= self._max_attempts
        ):
            raise KycLockedError(
                f"customer {customer_id} is locked after {latest.attempt_number} KYC attempts; "
                "contact support"
            )

        if self._kyc_port is None:
            raise KycPortNotConfiguredError(
                "start_verification requires a KycPort; this KycService was built without one"
            )
        handle = self._kyc_port.create_verification_session(customer_id=str(customer_id))

        attempt_number = 1 if latest is None else latest.attempt_number + 1

        session_row = KycSession(
            customer_id=customer_id,
            provider_session_id=handle.provider_session_id,
            status=KycSessionStatus.PENDING,
            attempt_number=attempt_number,
        )
        self._uow.kyc_sessions.add(session_row)
        return handle

    def apply_verification_verdict(
        self, *, provider_session_id: str, stripe_status: str
    ) -> uuid.UUID | None:
        """S2 §4's state machine. Returns `customer_id` on a terminal verdict, `None` if still pending."""
        session_row = self._uow.kyc_sessions.get_by_provider_session_id(provider_session_id)
        if session_row is None:
            raise CustomerNotFoundError(
                f"no kyc_session found for provider_session_id={provider_session_id!r}"
            )

        mapped_status = map_verification_session_status(
            stripe_status,
            attempt_number=session_row.attempt_number,
            max_attempts=self._max_attempts,
        )
        if mapped_status is KycSessionStatus.PENDING:
            return None

        self._uow.kyc_sessions.resolve(
            session_row, status=mapped_status, resolved_at=self._now()
        )

        customer = self._uow.customers.get_by_id(session_row.customer_id)
        if customer is None:
            raise CustomerNotFoundError(f"no customer found for id={session_row.customer_id!r}")
        customer.kyc_status = (
            KycStatus.approved if mapped_status is KycSessionStatus.APPROVED else KycStatus.rejected
        )
        return session_row.customer_id
