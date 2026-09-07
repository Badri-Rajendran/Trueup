"""Assembles a customer's tax-lot read model: every lot ever opened, enriched with current market
value, unrealized gain, wash-sale-disallowed loss, and per-sale consumption history (S8 §3, data
owned by S5). Mirrors FeeSummaryService's shape: a thin dataclass-returning assembly layer, called
by a thin controller that builds the Pydantic view.

Batches every N+1-shaped lookup (consumptions, securities, wash-sale adjustments) across the whole
lot list. The one per-security loop this service runs (daily closes) mirrors
ValuationService.value_book's own established idiom for "no batch daily-close repository method
exists" -- a customer's distinct held securities is a small, rate-limit-bounded set (GET /lots is
capped at 60 req/min), so this is not the N+1 pattern the batched lookups above are eliminating.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.core.money import Money, Units

if TYPE_CHECKING:
    import uuid
    from datetime import date

    from app.core.money import Price
    from app.models.ledger.lot_consumption import LotConsumption
    from app.models.ledger.tax_lot import TaxLot
    from app.services.lots.uow import LotsUnitOfWork


@dataclass(frozen=True, slots=True)
class LotSummary:
    lot: TaxLot
    symbol: str
    realized_gain_loss: Money
    is_provisional: bool
    current_price: Price | None
    market_value: Money | None
    unrealized_gain_loss: Money | None
    wash_sale_disallowed: Money
    consumptions: list[LotConsumption]


@dataclass(frozen=True, slots=True)
class LotsSummary:
    lots: list[LotSummary]


class LotsSummaryService:
    def __init__(self, uow: LotsUnitOfWork) -> None:
        self._uow = uow

    def summarize(self, customer_id: uuid.UUID, *, as_of_date: date) -> LotsSummary:
        """`as_of_date` is resolved by the caller via MarketClock (matching
        ValuationService.value_book's controller-resolves-the-date precedent) -- this service never
        converts a UTC instant into a market day itself."""
        lots = self._uow.tax_lots.list_for_customer(customer_id)
        lot_ids = [lot.id for lot in lots]

        consumptions_by_lot: dict[uuid.UUID, list[LotConsumption]] = defaultdict(list)
        for consumption in self._uow.lot_consumptions.list_for_lots(lot_ids):
            consumptions_by_lot[consumption.tax_lot_id].append(consumption)

        securities_by_id = {
            s.id: s
            for s in self._uow.securities.list_by_ids(list({lot.security_id for lot in lots}))
        }

        wash_sale_by_lot: dict[uuid.UUID, Money] = defaultdict(lambda: Money("0.00"))
        for adj in self._uow.wash_sale_adjustments.list_for_replacement_lots(lot_ids):
            wash_sale_by_lot[adj.replacement_tax_lot_id] = (
                wash_sale_by_lot[adj.replacement_tax_lot_id] + adj.disallowed_amount
            )

        open_security_ids = {lot.security_id for lot in lots if lot.quantity_remaining > Units("0")}
        price_by_security: dict[uuid.UUID, Price] = {}
        for security_id in open_security_ids:
            close = self._uow.daily_closes.latest_confirmed(
                security_id=security_id, market_date=as_of_date
            )
            if close is not None:
                price_by_security[security_id] = close.close_price

        items: list[LotSummary] = []
        for lot in lots:
            lot_consumptions = consumptions_by_lot.get(lot.id, [])
            realized_gain_loss = Money("0.00")
            for consumption in lot_consumptions:
                realized_gain_loss += consumption.realized_gain_loss

            security = securities_by_id.get(lot.security_id)
            current_price = price_by_security.get(lot.security_id)

            market_value: Money | None = None
            unrealized_gain_loss: Money | None = None
            if current_price is not None and lot.quantity_remaining > Units("0"):
                market_value = lot.quantity_remaining * current_price  # Units * Price -> Money
                unrealized_gain_loss = market_value - lot.adjusted_basis

            items.append(
                LotSummary(
                    lot=lot,
                    symbol=security.symbol if security is not None else "",
                    realized_gain_loss=realized_gain_loss,
                    is_provisional=any(c.is_provisional for c in lot_consumptions),
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_gain_loss=unrealized_gain_loss,
                    wash_sale_disallowed=wash_sale_by_lot.get(lot.id, Money("0.00")),
                    consumptions=lot_consumptions,
                )
            )

        return LotsSummary(lots=items)


__all__ = ["LotSummary", "LotsSummary", "LotsSummaryService"]
