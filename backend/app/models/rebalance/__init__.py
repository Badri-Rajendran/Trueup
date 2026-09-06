"""Rebalancing aggregates (S9) -- model portfolios, their target weights, and each customer's
current model assignment."""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.rebalance.customer_model_assignment import CustomerModelAssignmentRepository
from app.models.rebalance.model_portfolio import ModelPortfolioRepository
from app.models.rebalance.target_weight import TargetWeightRepository


class RebalanceModelsUnitOfWork(UnitOfWork):
    """A `UnitOfWork` exposing the repositories S9 owns (S0 §5's documented extension mechanism)."""

    @cached_property
    def model_portfolios(self) -> ModelPortfolioRepository:
        return ModelPortfolioRepository(self)

    @cached_property
    def target_weights(self) -> TargetWeightRepository:
        return TargetWeightRepository(self)

    @cached_property
    def customer_model_assignments(self) -> CustomerModelAssignmentRepository:
        return CustomerModelAssignmentRepository(self)


__all__ = ["RebalanceModelsUnitOfWork"]
