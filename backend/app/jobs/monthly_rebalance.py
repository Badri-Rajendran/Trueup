"""`MonthlyRebalanceJob` (S9 §7) — for each assigned customer, evaluates drift and submits
whatever orders `RebalanceOrderService` generates, via `OrderService` (S9 §6).
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
    """Admin/worker-role UoW for the job's own writes."""


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
        if self._market_date is None:  # pragma: no cover - defensive
            raise RuntimeError("MonthlyRebalanceJob.perform() called before run()")
        market_date = self._market_date

        with self._work_uow_factory() as uow:
            settings = get_settings()
            drift_evaluator = DriftEvaluationService(uow, drift_band_pct=settings.drift_band_pct)
            cash_policy = CashPolicyService(uow, holds_provider=OrderHoldsProvider(uow))
            order_service = OrderService(
                uow,
                hold_service=ApprovalHoldService(uow),
                cash_policy=cash_policy,
                approval_threshold_usd=settings.order_approval_threshold_usd,
                now=self._now,
            )
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
