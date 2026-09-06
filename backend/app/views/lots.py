"""Response schemas for `app/controllers/api/lots.py` (S8 §3, data owned by S5).

Explicit allow-lists only, never a raw entity (`app/views/` may not import `app/models/`,
`lint-imports`'s `views-are-not-entities` contract). `adjusted_basis`/`realized_gain_loss` are
always the wash-sale-**adjusted** figures (S5 §5's mutate-in-place design) -- this module has no
field for the pre-adjustment amount at all, so there is no raw figure a caller could reach for by
mistake (S5's own explicit warning against ever surfacing it).
"""

from __future__ import annotations

from datetime import date, datetime  # noqa: TC003 -- Pydantic resolves field annotations eagerly.

from pydantic import BaseModel

from app.core.money import Money, Units  # noqa: TC001


class LotResponse(BaseModel):
    """One `tax_lot` row (S5 §3.1), enriched with its own `lot_consumption` rows' aggregated
    realized gain and provisional status (S5 §7 edge case 1: a lot's consumptions are summed,
    while each one's provisional flag is preserved for display via `is_provisional` here being
    true if *any* of them still is)."""

    id: str
    security_id: str
    symbol: str
    quantity_opened: Units
    quantity_remaining: Units
    original_cost_basis: Money
    adjusted_basis: Money
    realized_gain_loss: Money
    is_provisional: bool
    acquired_at: date
    designation: str
    designation_window_closes_at: datetime


class LotsListResponse(BaseModel):
    lots: list[LotResponse]


__all__ = ["LotResponse", "LotsListResponse"]
