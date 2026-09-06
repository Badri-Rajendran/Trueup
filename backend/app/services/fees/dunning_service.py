"""`DunningService` (S10 §5, ADR 10, FR-48) — the retry/backoff/exhaustion state machine behind a
failed fee charge.

Deliberately owns only the *bookkeeping* (attempt counting, backoff scheduling, the
`retrying -> exhausted` transition) -- the actual "call Stripe again" step is
`FeeChargeService.attempt_charge`, reused unchanged for both the first attempt and every retry
(`DunningRetryJob` calls it directly). Splitting it this way avoids a circular import
(`FeeChargeService` already depends on this module to start dunning on a first failure) and matches
this codebase's own precedent of a state-machine service that never itself performs the I/O its
transitions react to (`AccountApprovalService` never calls Stripe/Plaid directly either).

Exponential backoff, doubling each attempt from a configurable base -- a defensible engineering
default (`DUNNING_BACKOFF_BASE_HOURS`), flagged for business/compliance review before go-live, same
posture as `KYC_MAX_ATTEMPTS`/the deposit caps (`DECISION-LOG.md`'s Assumptions table).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from app.models.fees.dunning_state import DunningState, DunningStatus
from app.models.fees.fee_charge import FeeChargeStatus

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.models.fees.fee_charge import FeeCharge
    from app.services.fees.uow import FeesUnitOfWork


def compute_backoff(attempt_number: int, *, base_hours: int) -> timedelta:
    """`attempt_number` is 1-indexed (the attempt that just failed); the delay before the *next*
    attempt doubles each time: `base_hours * 2**(attempt_number - 1)`."""
    if attempt_number < 1:
        raise ValueError("attempt_number must be at least 1")
    return timedelta(hours=base_hours * (2 ** (attempt_number - 1)))


class DunningService:
    def __init__(
        self,
        uow: FeesUnitOfWork,
        *,
        max_attempts: int,
        backoff_base_hours: int = 24,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._uow = uow
        self._max_attempts = max_attempts
        self._backoff_base_hours = backoff_base_hours
        self._now = now

    def start(self, charge: FeeCharge) -> DunningState:
        """The first failure on a `fee_charge` (S10 §5: `on Stripe failure: ... DunningService.
        start(fee_charge_id) -- never reverses the accrual`). `fee_charge.status` is set by the
        caller (`FeeChargeService.apply_charge_failure`) before this runs."""
        dunning = DunningState(
            fee_charge_id=charge.id,
            customer_id=charge.customer_id,
            attempt_number=1,
            next_retry_at=self._now() + compute_backoff(1, base_hours=self._backoff_base_hours),
            max_attempts=self._max_attempts,
            status=DunningStatus.RETRYING,
        )
        self._uow.dunning_states.add(dunning)
        self._uow.session.flush()
        return dunning

    def record_retry_failure(self, dunning: DunningState, charge: FeeCharge) -> None:
        """A subsequent retry attempt also failed (S10 §5): bump `attempt_number`; exhaust once
        `max_attempts` is reached (`fee_charge.status` moves to `dunning`, a standing,
        customer-visible balance owed -- FR-48's "never silently dropped"), otherwise schedule the
        next backoff."""
        dunning.attempt_number += 1
        if dunning.attempt_number >= dunning.max_attempts:
            dunning.status = DunningStatus.EXHAUSTED
            charge.status = FeeChargeStatus.DUNNING
        else:
            dunning.next_retry_at = self._now() + compute_backoff(
                dunning.attempt_number, base_hours=self._backoff_base_hours
            )


__all__ = ["DunningService", "compute_backoff"]
