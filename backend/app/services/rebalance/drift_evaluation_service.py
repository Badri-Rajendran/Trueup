"""`DriftEvaluationService` (S9 §4) — evaluates one customer's current holdings against their
assigned model's target weights, on a **relative** tolerance band (S9 §5: a 20%-target holding
triggers at 19%/21%, not a flat +/-5 percentage-point band).

`evaluate()` never drives a trading decision off a `partial` valuation (S9 §4's explicit
requirement, composing with S4's own completeness flag): a `partial` `value_book`, or a missing
close for any security the assigned model targets, both make the whole evaluation `partial` with
no entries at all -- never a subset silently evaluated against incomplete prices.

Every target-weight security is priced directly from `daily_close` here (not only inferred through
`ValuationService.value_book`'s total), because a security the model targets but the customer does
not yet hold at all (the very first rebalance for a newly assigned customer, S9 §6's first-buy
case) never appears in `value_book`'s own position loop -- its price is only ever needed here, on
this path.
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
    """Raised when `evaluate()` is called for a customer with no `customer_model_assignment`
    row. `MonthlyRebalanceJob` (S9 §7) only ever calls this for customers it already knows are
    assigned -- this is a defensive guard, not an expected control-flow branch."""


@dataclass(frozen=True, slots=True)
class DriftEntry:
    """One holding evaluated against its target -- `security_id is None` means the implicit CASH
    holding (S9 §4's last line). `is_flagged`/`direction` are always populated, even for an
    unflagged entry, so the admin visibility endpoint (foundation spec §13's `admin/rebalance.py`)
    can show "how close," not just "in/out of band."""

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
    """Empty iff `completeness == "partial"`, or the book carries no value at all (S9 §8: nothing
    to rebalance against zero value, not an error)."""

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
            # A partial valuation is never traded against (S9 §4); a zero-value book has no
            # weight concept at all, and is treated the same way -- nothing to rebalance, not an
            # error (S9 §8's own framing for the "everything within band" case, applied here to
            # an equally quiescent starting state).
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
                # This security's price is unavailable on this date -- exactly the "never trade
                # off an incomplete price" rule S4 enforces for held positions, extended here to
                # a target the customer may not even hold yet.
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

        # A held security with no target at all in the current model (S9 §8 item 4: dropped from
        # the model, or never in it) -- a zero implicit target, always a full-exit sell once
        # flagged (the zero-target branch inside _build_entry).
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

        # The implicit CASH holding against its implicit target (S9 §4's last line): whatever
        # fraction of the model the named securities do not already claim, typically 0 for a
        # fully-invested model.
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
        """The pure comparison at the center of S9 §4/§5, isolated so the property table S9 §9
        calls for (exactly-at-target, the band-edge boundary, the zero-target branch) is unit
        testable with no database, and no `Money`/`Units`/`Price`, at all -- plain `Decimal` in,
        `bool` out.

        `> band` triggers; `== band` does not (S9 §9's documented boundary, tested at both edges).
        A zero target weight (S9 §8 item 4: dropped from the model) has no ratio to take a
        *relative* drift against -- it is flagged whenever anything is actually held (a nonzero
        `current_weight_pct`, since `total_value != 0` is already guaranteed by the only caller),
        and never otherwise, matching the spec's "always a 100%-relative drift" framing without
        dividing by zero to get there.
        """
        if target_weight_pct == 0:
            return current_weight_pct != 0
        relative_drift = (current_weight_pct - target_weight_pct) / target_weight_pct
        return abs(relative_drift) > drift_band_pct


__all__ = ["DriftEntry", "DriftEvaluation", "DriftEvaluationService", "NoAssignedModelError"]
