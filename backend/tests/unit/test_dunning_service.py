"""`DunningService` (S10 §5, FR-48) — backoff/exhaustion sequencing, pure logic, no database."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.core.money import Money
from app.models.fees.dunning_state import DunningState, DunningStatus
from app.models.fees.fee_charge import FeeCharge, FeeChargeStatus
from app.services.fees.dunning_service import DunningService, compute_backoff

_FIXED_NOW = datetime(2026, 9, 5, tzinfo=UTC)


class _FakeDunningRepo:
    def add(self, dunning: DunningState) -> None:
        self.added = dunning


class _FakeSession:
    def flush(self) -> None:
        pass


class _FakeUow:
    def __init__(self) -> None:
        self.dunning_states = _FakeDunningRepo()
        self.session = _FakeSession()


def _charge() -> FeeCharge:
    return FeeCharge(
        id=uuid.uuid4(),
        customer_id=uuid.uuid4(),
        billing_period_start=datetime(2026, 8, 1, tzinfo=UTC).date(),
        billing_period_end=datetime(2026, 8, 31, tzinfo=UTC).date(),
        total_accrued=Money("10.00"),
        status=FeeChargeStatus.FAILED,
    )


def test_compute_backoff_doubles_each_attempt() -> None:
    assert compute_backoff(1, base_hours=24) == timedelta(hours=24)
    assert compute_backoff(2, base_hours=24) == timedelta(hours=48)
    assert compute_backoff(3, base_hours=24) == timedelta(hours=96)
    assert compute_backoff(4, base_hours=24) == timedelta(hours=192)


def test_compute_backoff_rejects_attempt_number_below_one() -> None:
    with pytest.raises(ValueError, match="attempt_number"):
        compute_backoff(0, base_hours=24)


def test_start_creates_a_retrying_state_at_attempt_one() -> None:
    uow = _FakeUow()
    service = DunningService(uow, max_attempts=4, now=lambda: _FIXED_NOW)  # type: ignore[arg-type]
    charge = _charge()

    dunning = service.start(charge)

    assert dunning.attempt_number == 1
    assert dunning.status is DunningStatus.RETRYING
    assert dunning.next_retry_at == _FIXED_NOW + timedelta(hours=24)
    assert dunning.max_attempts == 4


def test_record_retry_failure_schedules_the_next_backoff_below_max_attempts() -> None:
    uow = _FakeUow()
    service = DunningService(uow, max_attempts=4, now=lambda: _FIXED_NOW)  # type: ignore[arg-type]
    charge = _charge()
    dunning = DunningState(
        fee_charge_id=charge.id,
        customer_id=charge.customer_id,
        attempt_number=1,
        next_retry_at=_FIXED_NOW,
        max_attempts=4,
        status=DunningStatus.RETRYING,
    )

    service.record_retry_failure(dunning, charge)

    assert dunning.attempt_number == 2
    assert dunning.status is DunningStatus.RETRYING
    assert dunning.next_retry_at == _FIXED_NOW + timedelta(hours=48)
    assert charge.status is FeeChargeStatus.FAILED  # unchanged -- still auto-retrying


def test_record_retry_failure_exhausts_at_max_attempts() -> None:
    """FR-48: exhaustion is a standing, customer-visible balance owed -- `fee_charge.status`
    moves to `dunning`, never silently dropped."""
    uow = _FakeUow()
    service = DunningService(uow, max_attempts=3, now=lambda: _FIXED_NOW)  # type: ignore[arg-type]
    charge = _charge()
    dunning = DunningState(
        fee_charge_id=charge.id,
        customer_id=charge.customer_id,
        attempt_number=2,
        next_retry_at=_FIXED_NOW,
        max_attempts=3,
        status=DunningStatus.RETRYING,
    )

    service.record_retry_failure(dunning, charge)

    assert dunning.attempt_number == 3
    assert dunning.status is DunningStatus.EXHAUSTED
    assert charge.status is FeeChargeStatus.DUNNING
