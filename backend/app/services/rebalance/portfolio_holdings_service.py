"""`PortfolioHoldingsService` (Portfolio page redesign, ADR 26 context) — a thin per-security
holdings read model over `DriftEvaluationService.evaluate()` (S9 §4).

Today `DriftEvaluationService` is only reachable via the adviser/admin-only
`GET /api/v1/admin/rebalance/<customer_id>` route (`app/controllers/admin/rebalance.py`). This
service exposes the exact same live evaluation to the customer who owns the holdings, in the shape
`GET /api/v1/portfolios/holdings` needs -- it adds no new valuation logic, it only reshapes
`DriftEvaluation`'s entries into a per-security line (`units`, derived from `Money / Price ->
Units`, ADR 16) and carries `completeness` through unchanged, matching `ValuationService`/
`DriftEvaluationService`'s own discipline: a partial evaluation is never presented as "you hold
nothing" (S4 §9, NFR-6).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.services.rebalance.drift_evaluation_service import DriftEvaluationService

if TYPE_CHECKING:
    import uuid
    from datetime import date
    from decimal import Decimal

    from app.core.money import Money, Price, Units
    from app.services.rebalance.drift_evaluation_service import DriftEntry
    from app.services.rebalance.uow import RebalanceUnitOfWork
    from app.services.valuation.valuation_service import Completeness


@dataclass(frozen=True, slots=True)
class HoldingLine:
    """One held-or-targeted security; `security_id is None` is the implicit CASH line
    (`DriftEntry`'s own convention). A security dropped from the model still appears here with
    `target_weight_pct == 0` -- `DriftEvaluationService.evaluate()` already guarantees this, this
    service only reshapes it."""

    security_id: uuid.UUID | None
    units: Units | None
    price: Price | None
    market_value: Money
    current_weight_pct: Decimal
    target_weight_pct: Decimal
    drift_pct: Decimal
    is_flagged: bool


@dataclass(frozen=True, slots=True)
class PortfolioHoldings:
    customer_id: uuid.UUID
    as_of_date: date
    completeness: Completeness
    total_value: Money
    holdings: tuple[HoldingLine, ...]


class PortfolioHoldingsService:
    def __init__(self, uow: RebalanceUnitOfWork, *, drift_band_pct: Decimal) -> None:
        self._drift = DriftEvaluationService(uow, drift_band_pct=drift_band_pct)

    def holdings(self, customer_id: uuid.UUID, as_of_date: date) -> PortfolioHoldings:
        evaluation = self._drift.evaluate(customer_id, as_of_date)
        return PortfolioHoldings(
            customer_id=evaluation.customer_id,
            as_of_date=evaluation.as_of_date,
            completeness=evaluation.completeness,
            total_value=evaluation.total_value,
            holdings=tuple(self._to_line(entry) for entry in evaluation.entries),
        )

    @staticmethod
    def _to_line(entry: DriftEntry) -> HoldingLine:
        units = (
            entry.current_market_value / entry.price if entry.price is not None else None
        )
        return HoldingLine(
            security_id=entry.security_id,
            units=units,
            price=entry.price,
            market_value=entry.current_market_value,
            current_weight_pct=entry.current_weight_pct,
            target_weight_pct=entry.target_weight_pct,
            drift_pct=entry.current_weight_pct - entry.target_weight_pct,
            is_flagged=entry.is_flagged,
        )


__all__ = ["HoldingLine", "PortfolioHoldings", "PortfolioHoldingsService"]
