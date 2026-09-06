"""Retry/backoff/exhaustion state machine for a failed fee charge (S10 §5, ADR 10, FR-48).

Owns bookkeeping only; `FeeChargeService.attempt_charge` performs the actual retry call.
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
    """1-indexed `attempt_number`; delay doubles each time: `base_hours * 2**(attempt_number - 1)`."""
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
        """First failure on a `fee_charge` (S10 §5); never reverses the accrual."""
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
        """A retry attempt failed (S10 §5): bump attempt count, exhaust or reschedule backoff."""
        dunning.attempt_number += 1
        if dunning.attempt_number >= dunning.max_attempts:
            dunning.status = DunningStatus.EXHAUSTED
            charge.status = FeeChargeStatus.DUNNING
        else:
            dunning.next_retry_at = self._now() + compute_backoff(
                dunning.attempt_number, base_hours=self._backoff_base_hours
            )


__all__ = ["DunningService", "compute_backoff"]
