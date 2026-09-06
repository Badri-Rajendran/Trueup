"""Stand-in `HoldsProvider` (S1 §5) until S3's real one is wired in."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.money import Money

if TYPE_CHECKING:
    import uuid


class NullHoldsProvider:
    """Implements `HoldsProvider` with zero holds and zero open buy commitments."""

    def holds(self, customer_id: uuid.UUID) -> Money:
        return Money("0.00")

    def open_buy_commitments(self, customer_id: uuid.UUID) -> Money:
        return Money("0.00")
