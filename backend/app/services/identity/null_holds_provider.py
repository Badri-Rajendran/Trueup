"""`NullHoldsProvider` — a stand-in `HoldsProvider` (S1 §5) until S3 wires the real one.

`CashPolicyService`'s own module docstring is explicit that there is no default `HoldsProvider`,
since a silent "always zero" implementation would produce a wrong `investable`/`withdrawable`
figure forever if a caller forgot to wire the real one. This class is the opposite of silent: it is
named, documented, and injected explicitly at the funding controllers' wiring point -- the one
place that needs to change, with no change to `WithdrawalService`/`DepositService` themselves, once
S3's `ApprovalHoldService` exists and a real `HoldsProvider` replaces this one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.money import Money

if TYPE_CHECKING:
    import uuid


class NullHoldsProvider:
    """Implements `HoldsProvider` (structural) with zero holds and zero open buy commitments --
    correct only because S3's order-approval-hold and open-buy-commitment mechanisms do not exist
    yet. Replace at the wiring point in `app/controllers/api/funding.py`, not here."""

    def holds(self, customer_id: uuid.UUID) -> Money:
        return Money("0.00")

    def open_buy_commitments(self, customer_id: uuid.UUID) -> Money:
        return Money("0.00")
