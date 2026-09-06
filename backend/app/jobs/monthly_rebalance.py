"""`MonthlyRebalanceJob` (S9 §7) — for each customer with an assigned model portfolio, evaluates
drift and submits whatever orders `RebalanceOrderService` generates, through the identical
`OrderService` path a customer's own order takes (S9 §6).

Reuses `DailyValuationJob`/`MorningReconciliationJob`'s documented `ScheduledJob.perform()`
argument-gap workaround (`app/jobs/daily_valuation.py`'s own module docstring): `run()` stashes
`market_date` on the instance before delegating to `super().run()`, and `perform()` opens its own
separate `UnitOfWork` for its actual writes.

**One transaction for the whole run, matching the existing job precedent exactly** (both
`DailyValuationJob` and `MorningReconciliationJob` do all of their work in one `UnitOfWork`, one
commit) rather than one transaction per customer -- consistency with the only precedent this
codebase has for a scheduled job's transaction shape, not a new pattern invented here. Within that
one transaction, a customer found ineligible at order-creation time (`CustomerNotEligibleError` --
suspended between assignment and this run, S3 §7 case 2's re-check applied here) is logged and
skipped, not allowed to abort every other customer's rebalance in the same run; any other,
unexpected exception is not caught here and propagates to `ScheduledJob.run()`'s own handler,
which records the whole `job_run` as `failed` -- a genuine bug should fail loudly, an expected
per-customer ineligibility should not take the rest of the run down with it.

`market_date` is used directly as the valuation "as of" date (matching
`ValuationService.value_book`'s own `as_of_date` contract) -- S9's monthly cadence has no separate
notion of a settlement lag the way T+1 trade settlement does; "today's" holdings are evaluated
against "today's" model.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from app.config import get_settings
from app.core.db import DbRole
from app.core.logging import get_logger
from app.core.uow import SessionRole
from app.jobs.base import JobOutcome, ScheduledJob, default_job_uow
from app.models.ops.job_run import JobCadence
from app.services.ledger.cash_policy_service import CashPolicyService
from app.services.orders.approval_hold_service import ApprovalHoldService
from app.services.orders.holds_provider import OrderHoldsProvider
from app.services.orders.order_service import CustomerNotEligibleError, OrderService
from app.services.rebalance.drift_evaluation_service import DriftEvaluationService
from app.services.rebalance.rebalance_order_service import RebalanceOrderService, real_order_placer
from app.services.rebalance.uow import RebalanceUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Callable

    from app.jobs.base import JobUnitOfWork

log = get_logger(__name__)


class _RebalanceWorkUnitOfWork(RebalanceUnitOfWork):
    """Admin/worker-role UoW for the job's own writes -- see module docstring's flagged gap."""


def _default_work_uow_factory() -> _RebalanceWorkUnitOfWork:
    return _RebalanceWorkUnitOfWork(customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.WORKER)


class MonthlyRebalanceJob(ScheduledJob):
    job_name = "monthly_rebalance"
    cadence = JobCadence.MONTHLY

    def __init__(
        self,
        *,
        uow_factory: Callable[[], JobUnitOfWork] = default_job_uow,
        work_uow_factory: Callable[[], _RebalanceWorkUnitOfWork] = _default_work_uow_factory,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        super().__init__(uow_factory=uow_factory, now=now)
        self._work_uow_factory = work_uow_factory
        self._market_date: date | None = None

    def run(self, *, market_date: date) -> JobOutcome:
        self._market_date = market_date
        return super().run(market_date=market_date)

    def perform(self) -> None:
        if self._market_date is None:  # pragma: no cover - defensive; run() always sets it first
            raise RuntimeError("MonthlyRebalanceJob.perform() called before run()")
        market_date = self._market_date

        with self._work_uow_factory() as uow:
            settings = get_settings()
            drift_evaluator = DriftEvaluationService(uow, drift_band_pct=settings.drift_band_pct)
            order_service = OrderService(
                uow,
                hold_service=ApprovalHoldService(uow),
                approval_threshold_usd=settings.order_approval_threshold_usd,
                now=self._now,
            )
            cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
            rebalance_orders = RebalanceOrderService(
                order_placer=real_order_placer(order_service),
                cash_provider=cash_policy,
                cash_buffer_pct=settings.rebalance_cash_buffer_pct,
            )

            for assignment in uow.customer_model_assignments.list_all():
                try:
                    evaluation = drift_evaluator.evaluate(assignment.customer_id, market_date)
                    rebalance_orders.generate_orders(evaluation)
                except CustomerNotEligibleError as exc:
                    log.warning(
                        "monthly_rebalance.customer_skipped",
                        customer_id=str(assignment.customer_id),
                        reason=exc.reason,
                    )

            uow.commit()


__all__ = ["MonthlyRebalanceJob"]
