"""Performance-fee aggregates (S10, ADR 10) -- `high_water_mark`, `fee_accrual`, `fee_charge`,
`dunning_state`, `fee_restatement_disclosure`.

`FeesModelsUnitOfWork` is the same shape as `RestatementModelsUnitOfWork`/
`RebalanceModelsUnitOfWork`: a thin models-layer mixin meant to be composed by the services-layer
`FeesUnitOfWork` (`app/services/fees/uow.py`), S0 §5's documented extension mechanism.
"""

from __future__ import annotations

from functools import cached_property

from app.core.uow import UnitOfWork
from app.models.fees.dunning_state import DunningStateRepository
from app.models.fees.fee_accrual import FeeAccrualRepository
from app.models.fees.fee_charge import FeeChargeRepository
from app.models.fees.fee_restatement_disclosure import FeeRestatementDisclosureRepository
from app.models.fees.high_water_mark import HighWaterMarkRepository
from app.models.fees.payment_method import PaymentMethodRepository


class FeesModelsUnitOfWork(UnitOfWork):
    @cached_property
    def high_water_marks(self) -> HighWaterMarkRepository:
        return HighWaterMarkRepository(self)

    @cached_property
    def fee_accruals(self) -> FeeAccrualRepository:
        return FeeAccrualRepository(self)

    @cached_property
    def fee_charges(self) -> FeeChargeRepository:
        return FeeChargeRepository(self)

    @cached_property
    def dunning_states(self) -> DunningStateRepository:
        return DunningStateRepository(self)

    @cached_property
    def fee_restatement_disclosures(self) -> FeeRestatementDisclosureRepository:
        return FeeRestatementDisclosureRepository(self)

    @cached_property
    def payment_methods(self) -> PaymentMethodRepository:
        return PaymentMethodRepository(self)


__all__ = ["FeesModelsUnitOfWork"]
