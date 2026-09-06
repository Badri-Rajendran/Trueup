"""Evaluates one customer's holdings against their model's target weights on a relative band
(S9 §4/§5).

`evaluate()` never drives a trading decision off a `partial` valuation; a missing close for
any targeted security makes the whole evaluation `partial` with no entries.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Literal

from app.core.money import Money, Units
from app.services.valuation.valuation_service import ValuationService

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.core.money import Price
    from app.services.rebalance.uow import RebalanceUnitOfWork
    from app.services.valuation.valuation_service import Completeness

Direction = Literal["buy", "sell"]


class NoAssignedModelError(RuntimeError):
    """Raised when `evaluate()` is called for a customer with no `customer_model_assignment` row."""


@dataclass(frozen=True, slots=True)
class DriftEntry:
    """One holding evaluated against its target; `security_id is None` means implicit CASH
    (S9 §4)."""

    security_id: uuid.UUID | None
    current_market_value: Money
    target_market_value: Money
    current_weight_pct: Decimal
    target_weight_pct: Decimal
    price: Price | None
    is_flagged: bool
    direction: Direction


@dataclass(frozen=True, slots=True)
class DriftEvaluation:
    customer_id: uuid.UUID
    model_portfolio_id: uuid.UUID
    as_of_date: date
    completeness: Completeness
    total_value: Money
    entries: tuple[DriftEntry, ...]
    """Empty iff `completeness == "partial"`, or the book carries no value at all (S9 §8)."""

    @property
    def flagged(self) -> tuple[DriftEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_flagged)


class DriftEvaluationService:
    def __init__(self, uow: RebalanceUnitOfWork, *, drift_band_pct: Decimal) -> None:
        self._uow = uow
        self._drift_band_pct = drift_band_pct
        self._valuation = ValuationService(uow)

    def evaluate(self, customer_id: uuid.UUID, as_of_date: date) -> DriftEvaluation:
        assignment = self._uow.customer_model_assignments.get_by_customer(customer_id)
        if assignment is None:
            raise NoAssignedModelError(f"no model assigned for customer_id={customer_id!r}")
        model_portfolio_id = assignment.model_portfolio_id

        book = self._valuation.value_book(customer_id, as_of_date)
        if book.completeness != "complete" or book.total_value == Money("0.00"):
            # A partial valuation is never traded against (S9 §4); zero value is a no-op too.
            return DriftEvaluation(
                customer_id=customer_id,
                model_portfolio_id=model_portfolio_id,
                as_of_date=as_of_date,
                completeness=book.completeness,
                total_value=book.total_value,
                entries=(),
            )

        targets = self._uow.target_weights.list_for_model(model_portfolio_id)
        current_units = self._valuation.position_units(customer_id, as_of_date)
        cash_balance = self._valuation.cash_balance(customer_id, as_of_date)

        entries: list[DriftEntry] = []
        accounted_target_pct = Decimal("0")
        seen_security_ids: set[uuid.UUID] = set()

        for target in targets:
            seen_security_ids.add(target.security_id)
            close = self._uow.daily_closes.latest_confirmed(
                security_id=target.security_id, market_date=as_of_date
            )
            if close is None:
                # Price unavailable on this date; never trade off an incomplete price (S4).
                return DriftEvaluation(
                    customer_id=customer_id,
                    model_portfolio_id=model_portfolio_id,
                    as_of_date=as_of_date,
                    completeness="partial",
                    total_value=book.total_value,
                    entries=(),
                )
            units_held = current_units.get(target.security_id, Units("0"))
            current_value = units_held * close.close_price
            entries.append(
                self._build_entry(
                    security_id=target.security_id,
                    current_value=current_value,
                    target_weight_pct=target.weight_pct,
                    total_value=book.total_value,
                    price=close.close_price,
                )
            )
            accounted_target_pct += target.weight_pct

        # A held security dropped from the model gets a zero implicit target (S9 §8 item 4).
        for security_id, units_held in current_units.items():
            if security_id in seen_security_ids:
                continue
            close = self._uow.daily_closes.latest_confirmed(
                security_id=security_id, market_date=as_of_date
            )
            if close is None:
                return DriftEvaluation(
                    customer_id=customer_id,
                    model_portfolio_id=model_portfolio_id,
                    as_of_date=as_of_date,
                    completeness="partial",
                    total_value=book.total_value,
                    entries=(),
                )
            current_value = units_held * close.close_price
            entries.append(
                self._build_entry(
                    security_id=security_id,
                    current_value=current_value,
                    target_weight_pct=Decimal("0"),
                    total_value=book.total_value,
                    price=close.close_price,
                )
            )

        # The implicit CASH holding against its implicit target (S9 §4's last line).
        cash_target_pct = Decimal("1") - accounted_target_pct
        entries.append(
            self._build_entry(
                security_id=None,
                current_value=cash_balance,
                target_weight_pct=cash_target_pct,
                total_value=book.total_value,
                price=None,
            )
        )

        return DriftEvaluation(
            customer_id=customer_id,
            model_portfolio_id=model_portfolio_id,
            as_of_date=as_of_date,
            completeness="complete",
            total_value=book.total_value,
            entries=tuple(entries),
        )

    def _build_entry(
        self,
        *,
        security_id: uuid.UUID | None,
        current_value: Money,
        target_weight_pct: Decimal,
        total_value: Money,
        price: Price | None,
    ) -> DriftEntry:
        target_value = target_weight_pct * total_value
        current_weight_pct = current_value / total_value
        is_flagged = self.is_out_of_band(
            current_weight_pct=current_weight_pct,
            target_weight_pct=target_weight_pct,
            drift_band_pct=self._drift_band_pct,
        )
        direction: Direction = "sell" if current_value > target_value else "buy"
        return DriftEntry(
            security_id=security_id,
            current_market_value=current_value,
            target_market_value=target_value,
            current_weight_pct=current_weight_pct,
            target_weight_pct=target_weight_pct,
            price=price,
            is_flagged=is_flagged,
            direction=direction,
        )

    @staticmethod
    def is_out_of_band(
        *,
        current_weight_pct: Decimal,
        target_weight_pct: Decimal,
        drift_band_pct: Decimal,
    ) -> bool:
        """Pure relative-drift comparison (S9 §4/§5): `> band` triggers, `== band` does not."""
        if target_weight_pct == 0:
            return current_weight_pct != 0
        relative_drift = (current_weight_pct - target_weight_pct) / target_weight_pct
        return abs(relative_drift) > drift_band_pct


__all__ = ["DriftEntry", "DriftEvaluation", "DriftEvaluationService", "NoAssignedModelError"]
