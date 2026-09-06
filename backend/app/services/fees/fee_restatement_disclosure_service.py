"""Implements `FeeDisclosureChecker` (S10 §6, FR-47): records a disclosure row for an already-charged
period a restatement touched. Never reopens or adjusts the charge itself (out of v1 scope, ADR 10)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from app.models.fees.fee_restatement_disclosure import FeeRestatementDisclosure

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.models.fees.fee_charge import FeeChargeRepository
    from app.models.fees.fee_restatement_disclosure import FeeRestatementDisclosureRepository


class FeeDisclosureCapableUnitOfWork(Protocol):
    @property
    def fee_charges(self) -> FeeChargeRepository: ...
    @property
    def fee_restatement_disclosures(self) -> FeeRestatementDisclosureRepository: ...


class FeeRestatementDisclosureService:
    """Implements `FeeDisclosureChecker` (structural — no inheritance required)."""

    def __init__(self, uow: FeeDisclosureCapableUnitOfWork) -> None:
        self._uow = uow

    def check_and_disclose(
        self,
        *,
        customer_id: uuid.UUID,
        period_start: date,
        period_end: date,
        restatement_event_id: uuid.UUID,
    ) -> None:
        charge = self._uow.fee_charges.has_succeeded_charge_for_period(
            customer_id, period_start=period_start, period_end=period_end
        )
        if charge is None:
            return
        self._uow.fee_restatement_disclosures.add(
            FeeRestatementDisclosure(
                customer_id=customer_id,
                fee_charge_id=charge.id,
                restatement_event_id=restatement_event_id,
            )
        )


__all__ = ["FeeRestatementDisclosureService"]
