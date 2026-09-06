"""`DunningRetryJob` (S10 §5, `continuous` cadence, foundation spec §9) — retries every
`fee_charge` currently in `dunning_state.status = retrying` whose `next_retry_at` is due.

Legitimately fires more than once per day as retries come due -- the `continuous` cadence carries
no daily/monthly uniqueness constraint on `job_run` for exactly that reason (`app/models/ops/
job_run.py`'s partial unique indexes are both `WHERE cadence IN ('daily', 'monthly')` only).

The due-rows read is its own short, read-only transaction; each retry then goes through
`FeeChargeOutboxHandler.charge_fee` -- the identical three-phase, no-I/O-in-transaction operation a
first attempt uses (S0 §5), never a fourth, retry-specific code path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.jobs.base import ScheduledJob, default_job_uow
from app.models.ops.job_run import JobCadence
from app.services.fees.uow import FeesUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.jobs.base import JobUnitOfWork
    from app.services.fees.fee_charge_outbox_handler import FeeChargeOutboxHandler


class _DunningRetryWorkUnitOfWork(FeesUnitOfWork):
    """Admin/worker-role UoW for the job's own reads."""


def _default_work_uow_factory() -> _DunningRetryWorkUnitOfWork:
    return _DunningRetryWorkUnitOfWork(
        customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER
    )


class DunningRetryJob(ScheduledJob):
    job_name = "dunning_retry"
    cadence = JobCadence.CONTINUOUS

    def __init__(
        self,
        *,
        outbox_handler: FeeChargeOutboxHandler,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[[], _DunningRetryWorkUnitOfWork] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._outbox_handler = outbox_handler
        self._work_uow_factory = work_uow_factory

    def perform(self) -> None:
        with self._work_uow_factory() as uow:
            due = uow.dunning_states.list_due(now=self._now())
            fee_charge_ids = [dunning.fee_charge_id for dunning in due]
            uow.commit()

        for fee_charge_id in fee_charge_ids:
            self._outbox_handler.charge_fee(fee_charge_id)


__all__ = ["DunningRetryJob"]
