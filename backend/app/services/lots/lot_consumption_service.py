"""Opens a tax lot per buy fill, consumes lots (FIFO/specific-ID, ADR 4) per sell fill, and posts
the `trade_buy`/`trade_sell` ledger entries (S5 §4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.money import Money, Units
from app.models.ledger.account import AccountRole
from app.models.ledger.journal_entry import JournalEntryType
from app.models.ledger.lot_consumption import LotConsumption
from app.models.ledger.settlement_obligation import SettlementObligation
from app.models.ledger.tax_lot import LotDesignation, TaxLot
from app.models.ops.inbound_event import InboundEventSource
from app.services.ledger.posting_service import PostingLeg, PostingService
from app.services.lots._shared import (
    get_or_create_customer_account,
    record_inbound_event,
    require_customer_account,
)
from app.services.lots.wash_sale_service import WashSaleService

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence
    from datetime import datetime

    from app.core.clock import MarketClock
    from app.core.money import Price
    from app.services.lots.uow import LotsUnitOfWork

_SETTLEMENT_TRADING_DAYS = 1
"""Trades settle T+1."""


class InsufficientLotsError(RuntimeError):
    """A sell fill's quantity exceeds every open lot's remaining quantity (S5 §7 edge case 6)."""


class UnknownTaxLotError(RuntimeError):
    """A specific-ID designation names a lot that doesn't exist or belongs to another customer/security."""


class LotConsumptionService:
    def __init__(
        self,
        uow: LotsUnitOfWork,
        *,
        market_clock: MarketClock,
        wash_sale_service: WashSaleService | None = None,
    ) -> None:
        self._uow = uow
        self._market_clock = market_clock
        self._posting_service = PostingService(uow)
        self._wash_sale_service = wash_sale_service or WashSaleService(uow)

    def record_buy_fill(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        execution_id: str,
        quantity: Units,
        price: Price,
        filled_at: datetime,
    ) -> TaxLot:
        """Opens a tax lot and posts the `trade_buy` entry (position_units/position_cost/cash)."""
        fill_date = self._market_clock.market_date(filled_at)
        cost = price * quantity

        units_account = get_or_create_customer_account(
            self._uow,
            customer_id=customer_id,
            role=AccountRole.POSITION_UNITS,
            security_id=security_id,
        )
        cost_account = get_or_create_customer_account(
            self._uow,
            customer_id=customer_id,
            role=AccountRole.POSITION_COST,
            security_id=security_id,
        )
        cash_account = require_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.CASH
        )

        entry_event = record_inbound_event(
            self._uow,
            source=InboundEventSource.ALPACA,
            kind="trade_buy_fill",
            payload={
                "customer_id": str(customer_id),
                "security_id": str(security_id),
                "execution_id": execution_id,
                "quantity": str(quantity),
                "price": str(price),
            },
        )
        entry = self._posting_service.post(
            entry_type=JournalEntryType.TRADE_BUY,
            effective_date=fill_date,
            source_event_id=entry_event.id,
            legs=[
                PostingLeg(account_id=units_account.id, quantity_units=quantity),
                PostingLeg(account_id=cost_account.id, amount_money=cost),
                PostingLeg(account_id=cash_account.id, amount_money=-cost),
            ],
        )

        settlement_date = self._market_clock.add_trading_days(fill_date, _SETTLEMENT_TRADING_DAYS)
        obligation_event = record_inbound_event(
            self._uow,
            source=InboundEventSource.ALPACA,
            kind="trade_buy_settlement_expected",
            payload={"execution_id": execution_id, "amount": str(cost)},
        )
        self._uow.settlement_obligations.add(
            SettlementObligation(
                journal_entry_id=entry.id,
                account_id=cash_account.id,
                amount_money=-cost,
                expected_settlement_date=settlement_date,
                source_event_id=obligation_event.id,
            )
        )

        window_closes_at = self._market_clock.session_close(settlement_date)
        if window_closes_at is None:  # pragma: no cover - defensive
            raise RuntimeError(
                f"expected_settlement_date {settlement_date} is not a trading day per the "
                "injected calendar -- MarketClock.add_trading_days should never produce this"
            )

        lot = TaxLot(
            customer_id=customer_id,
            security_id=security_id,
            opening_fill_execution_id=execution_id,
            quantity_opened=quantity,
            quantity_remaining=quantity,
            original_cost_basis=cost,
            adjusted_basis=cost,
            acquired_at=fill_date,
            designation=LotDesignation.UNSPECIFIED,
            designation_window_closes_at=window_closes_at,
        )
        self._uow.tax_lots.add(lot)
        self._uow.session.flush()

        self._wash_sale_service.on_buy_fill(lot)
        return lot

    def record_sell_fill(
        self,
        *,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        execution_id: str,
        quantity: Units,
        price: Price,
        filled_at: datetime,
        designated_lot_ids: Sequence[uuid.UUID] | None = None,
    ) -> list[LotConsumption]:
        """Consumes lots (FIFO default, specific-ID override -- ADR 4, S5 §4) and posts the
        `trade_sell` entry with realized gain/loss legs."""
        fill_date = self._market_clock.market_date(filled_at)
        lots = self._select_lots_to_consume(customer_id, security_id, designated_lot_ids)

        remaining_to_sell = quantity
        consumed_basis_total = Money("0.00")
        realized_total = Money("0.00")
        consumptions: list[LotConsumption] = []

        for lot in lots:
            if remaining_to_sell <= Units("0"):
                break
            take = min(lot.quantity_remaining, remaining_to_sell)
            if take <= Units("0"):
                continue

            per_unit_basis = lot.adjusted_basis / lot.quantity_remaining
            consumed_basis = per_unit_basis * take
            proceeds = price * take
            realized = proceeds - consumed_basis

            consumption = LotConsumption(
                closing_fill_execution_id=execution_id,
                tax_lot_id=lot.id,
                quantity_consumed=take,
                realized_gain_loss=realized,
                is_provisional=filled_at < lot.designation_window_closes_at,
                sale_date=fill_date,
            )
            self._uow.lot_consumptions.add(consumption)
            consumptions.append(consumption)

            lot.quantity_remaining = lot.quantity_remaining - take
            lot.adjusted_basis = lot.adjusted_basis - consumed_basis

            consumed_basis_total = consumed_basis_total + consumed_basis
            realized_total = realized_total + realized
            remaining_to_sell = remaining_to_sell - take

        if remaining_to_sell > Units("0"):
            raise InsufficientLotsError(
                f"sell fill for {quantity} of security {security_id} against customer "
                f"{customer_id} exceeds open lot quantity by {remaining_to_sell} (S5 §7 edge "
                "case 6)"
            )

        units_account = get_or_create_customer_account(
            self._uow,
            customer_id=customer_id,
            role=AccountRole.POSITION_UNITS,
            security_id=security_id,
        )
        cost_account = get_or_create_customer_account(
            self._uow,
            customer_id=customer_id,
            role=AccountRole.POSITION_COST,
            security_id=security_id,
        )
        cash_account = require_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.CASH
        )
        realized_gain_loss_account = get_or_create_customer_account(
            self._uow, customer_id=customer_id, role=AccountRole.REALIZED_GAIN_LOSS
        )
        proceeds_total = price * quantity

        entry_event = record_inbound_event(
            self._uow,
            source=InboundEventSource.ALPACA,
            kind="trade_sell_fill",
            payload={
                "customer_id": str(customer_id),
                "security_id": str(security_id),
                "execution_id": execution_id,
                "quantity": str(quantity),
                "price": str(price),
            },
        )
        entry = self._posting_service.post(
            entry_type=JournalEntryType.TRADE_SELL,
            effective_date=fill_date,
            source_event_id=entry_event.id,
            legs=[
                PostingLeg(account_id=units_account.id, quantity_units=-quantity),
                PostingLeg(account_id=cost_account.id, amount_money=-consumed_basis_total),
                PostingLeg(account_id=cash_account.id, amount_money=proceeds_total),
                PostingLeg(account_id=realized_gain_loss_account.id, amount_money=-realized_total),
            ],
        )

        settlement_date = self._market_clock.add_trading_days(fill_date, _SETTLEMENT_TRADING_DAYS)
        obligation_event = record_inbound_event(
            self._uow,
            source=InboundEventSource.ALPACA,
            kind="trade_sell_settlement_expected",
            payload={"execution_id": execution_id, "amount": str(proceeds_total)},
        )
        self._uow.settlement_obligations.add(
            SettlementObligation(
                journal_entry_id=entry.id,
                account_id=cash_account.id,
                amount_money=proceeds_total,
                expected_settlement_date=settlement_date,
                source_event_id=obligation_event.id,
            )
        )

        self._uow.session.flush()  # assigns each consumption.id before the wash-sale scan below
        for consumption in consumptions:
            if consumption.realized_gain_loss < Money("0.00"):
                self._wash_sale_service.on_loss_sale(
                    consumption, customer_id=customer_id, security_id=security_id
                )

        return consumptions

    # --- internals --------------------------------------------------------------------------

    def _select_lots_to_consume(
        self,
        customer_id: uuid.UUID,
        security_id: uuid.UUID,
        designated_lot_ids: Sequence[uuid.UUID] | None,
    ) -> list[TaxLot]:
        if not designated_lot_ids:
            return self._uow.tax_lots.lock_open_fifo(customer_id, security_id)

        locked = self._uow.tax_lots.lock_by_ids(designated_lot_ids)
        lots: list[TaxLot] = []
        for lot_id in designated_lot_ids:
            lot = locked.get(lot_id)
            if lot is None:
                raise UnknownTaxLotError(f"no tax lot found for id={lot_id!r}")
            if lot.customer_id != customer_id or lot.security_id != security_id:
                raise UnknownTaxLotError(
                    f"tax lot {lot_id!r} does not belong to customer {customer_id!r} / "
                    f"security {security_id!r}"
                )
            lot.designation = LotDesignation.SPECIFIC
            lots.append(lot)
        return lots


__all__ = ["InsufficientLotsError", "LotConsumptionService", "UnknownTaxLotError"]
