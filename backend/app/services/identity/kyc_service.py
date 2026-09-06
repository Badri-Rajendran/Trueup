"""`KycService` (S2 §4, ADR 9) — starts Stripe Identity verification sessions and applies the
provider's verdict once it arrives.

The verdict itself never arrives synchronously (`KycPort.create_verification_session` only starts
a session); `apply_verification_verdict` is what a webhook-triggered caller invokes once Stripe's
own event names the session and its new status (S2 §6).

`map_verification_session_status` -- ADR 9's status-mapping table -- lives here, in the service
layer, not in `app/integrations/stripe/`: `.importlinter`'s `services-use-ports-only` contract
forbids `app.services` from importing a concrete adapter module at all (S0 §3, DIP), and the
mapping is domain policy (which Stripe session statuses count as our `approved`/`rejected`/
`pending`), not a provider call -- it belongs on this side of the port regardless.
"""

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
    """ADR 9's status mapping: `requires_input`/`processing` -> `pending`, `verified` ->
    `approved`, `canceled` -> `rejected`, and `requires_input` past `KYC_MAX_ATTEMPTS` ->
    `rejected` (never a naive "not yet verified = rejected" simplification -- a `processing`
    session stuck indefinitely still reports `pending`, per ADR 9's explicit warning)."""
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
    """Raised when `start_verification` is called on a `KycService` built without a `KycPort` --
    the webhook path (`apply_verification_verdict` only) never needs one (S2 §4: the verdict never
    arrives through this port), so callers on that path may omit it entirely."""


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
        """S2 §5.1/§6: `POST /identity/kyc-sessions`. Always opens a fresh attempt -- S2 §9 defers
        the locked-`rejected` reopening gate to an out-of-scope adviser action; this method only
        guarantees `attempt_number` keeps advancing so that action has something to reopen."""
        if self._kyc_port is None:
            raise KycPortNotConfiguredError(
                "start_verification requires a KycPort; this KycService was built without one"
            )
        handle = self._kyc_port.create_verification_session(customer_id=str(customer_id))

        latest = self._uow.kyc_sessions.latest_for_customer(customer_id)
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
        """S2 §4's state machine, applied to the `kyc_session` row Stripe's own webhook names.

        A session Stripe reports as still `pending` (`requires_input`/`processing`, below the
        attempt cap) resolves to nothing here -- `KycSession.status` stays `pending` and no
        `resolve()` call happens, since `resolve()`'s single-transition guard (S2 §3.2) only
        permits a `pending -> terminal` move, never a no-op re-write of `pending` onto itself.

        Returns the affected `customer_id` once a terminal verdict is applied, `None` when the
        verdict is still `pending` -- the caller (the webhook controller) uses this to decide
        whether to also invoke `AccountApprovalService` for this customer.
        """
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
