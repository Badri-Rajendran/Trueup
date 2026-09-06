"""`WashSaleService` (S5 §5, ADR 11) — the reactive same-CUSIP wash-sale check.

Two symmetric entry points, matching ADR 11's "composes cleanly... no new temporal reasoning
required": `on_loss_sale` handles a buy that already happened before the sale (checked immediately),
`on_buy_fill` handles a buy arriving after an earlier loss sale (checked reactively when the buy
posts). Both funnel into `_apply_adjustment`, so the disallowance math and posting shape live in
exactly one place.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

from app.core.money import Money
from app.models.ledger.account import AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ledger.wash_sale_adjustment import WashSaleAdjustment
from app.models.ops.inbound_event import InboundEventSource
from app.models.restatement.restatement_event import RestatementTriggerType
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.lots._shared import get_or_create_customer_account, record_inbound_event
from app.services.restatement.restatement_service import RestatementService

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.models.ledger.lot_consumption import LotConsumption
    from app.models.ledger.tax_lot import TaxLot
    from app.services.lots.uow import LotsUnitOfWork

_WASH_SALE_WINDOW_DAYS = 30


class WashSaleService:
    def __init__(self, uow: LotsUnitOfWork) -> None:
        self._uow = uow
        self._posting_service = PostingService(uow)

    def on_loss_sale(
        self,
        consumption: LotConsumption,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
    ) -> None:
        """The trailing-window side: a same-CUSIP buy that already happened before this loss
        sale. Called once per loss-realizing `lot_consumption` a sell fill produces."""
        if consumption.realized_gain_loss >= Money("0.00"):
            return
        if self._uow.wash_sale_adjustments.exists_for_consumption(consumption.id):
            return

        window_start, window_end = self._window(consumption.sale_date)
        replacement_lot = self._uow.tax_lots.find_earliest_replacement_in_window(
            customer_id,
            security_id,
            window_start=window_start,
            window_end=window_end,
            exclude_lot_id=consumption.tax_lot_id,
        )
        if replacement_lot is None:
            return
        self._apply_adjustment(consumption, replacement_lot)

    def on_buy_fill(self, new_lot: TaxLot) -> None:
        """The forward-window side: a same-CUSIP buy landing after an earlier loss sale. Called
        once per buy fill, scanning that security's still-unadjusted loss consumptions."""
        window_start, window_end = self._window(new_lot.acquired_at)
        candidates = self._uow.lot_consumptions.find_unadjusted_losses_in_window(
            new_lot.customer_id,
            new_lot.security_id,
            window_start=window_start,
            window_end=window_end,
        )
        for consumption in candidates:
            if consumption.tax_lot_id == new_lot.id:
                continue  # a lot cannot be its own replacement
            self._apply_adjustment(consumption, new_lot)

    # --- internals --------------------------------------------------------------------------

    @staticmethod
    def _window(anchor: date) -> tuple[date, date]:
        return (
            anchor - timedelta(days=_WASH_SALE_WINDOW_DAYS),
            anchor + timedelta(days=_WASH_SALE_WINDOW_DAYS),
        )

    def _apply_adjustment(self, consumption: LotConsumption, replacement_lot: TaxLot) -> None:
        if self._uow.wash_sale_adjustments.exists_for_consumption(consumption.id):
            return  # already carried into a replacement by the other symmetric entry point

        disallowed = min(abs(consumption.realized_gain_loss), replacement_lot.original_cost_basis)

        realized_gain_loss_account = get_or_create_customer_account(
            self._uow, customer_id=replacement_lot.customer_id, role=AccountRole.REALIZED_GAIN_LOSS
        )
        position_cost_account = get_or_create_customer_account(
            self._uow,
            customer_id=replacement_lot.customer_id,
            role=AccountRole.POSITION_COST,
            security_id=replacement_lot.security_id,
        )

        event = record_inbound_event(
            self._uow,
            source=InboundEventSource.ALPACA,
            kind="wash_sale_adjustment",
            payload={
                "lot_consumption_id": str(consumption.id),
                "replacement_tax_lot_id": str(replacement_lot.id),
                "disallowed_amount": str(disallowed),
            },
        )
        entry = self._posting_service.post(
            entry_type=JournalEntryType.WASH_SALE_ADJUSTMENT,
            effective_date=replacement_lot.acquired_at,
            source_event_id=event.id,
            legs=[
                PostingLeg(account_id=realized_gain_loss_account.id, amount_money=-disallowed),
                PostingLeg(account_id=position_cost_account.id, amount_money=disallowed),
            ],
            memo="wash sale adjustment (ADR 11)",
        )

        self._uow.wash_sale_adjustments.add(
            WashSaleAdjustment(
                original_lot_consumption_id=consumption.id,
                replacement_tax_lot_id=replacement_lot.id,
                disallowed_amount=disallowed,
                journal_entry_id=entry.id,
            )
        )
        replacement_lot.adjusted_basis = replacement_lot.adjusted_basis + disallowed
        consumption.realized_gain_loss = consumption.realized_gain_loss + disallowed

        # S6 §4: react to the wash-sale-adjustment entry just posted, same transaction, same
        # session (RestatementService.restate() must see this not-yet-committed correction).
        RestatementService(self._uow).restate(
            customer_id=replacement_lot.customer_id,
            affected_date=replacement_lot.acquired_at,
            trigger_type=RestatementTriggerType.WASH_SALE_ADJUSTMENT,
            source_event_id=entry.source_event_id,
        )


__all__ = ["WashSaleService"]
