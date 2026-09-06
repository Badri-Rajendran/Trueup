"""`FakeBankAdapter` — the `BankPort` fake for `tests/contract/` (S2 §8) and every other test that
needs a Plaid stand-in with no network call.

The two `build_*_webhook_body` helpers are test helpers, not part of `BankPort`: they construct the
same JSON shape a real Plaid webhook delivers for the two failure modes S2 §7/§8 name explicitly --
`ITEM_LOGIN_REQUIRED` (FR-43) and a bounced ACH return (FR-6) -- so a test can exercise
`BankLinkService`/`DepositService`'s webhook-processing path without depending on Plaid at all.
"""

from __future__ import annotations

import itertools
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.integrations.ports import BankLinkHandle, LinkTokenHandle


class FakeBankAdapter:
    """Implements `BankPort` (structural — no inheritance required)."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self.exchanged_tokens: list[str] = []
        self.link_token_client_user_ids: list[str] = []

    def create_link_token(self, *, client_user_id: str) -> LinkTokenHandle:
        self.link_token_client_user_ids.append(client_user_id)
        n = next(self._counter)
        return LinkTokenHandle(
            link_token=f"link-sandbox-fake-{n}-{uuid.uuid4().hex[:8]}",
            expiration=datetime.now(UTC) + timedelta(hours=4),  # Plaid's own real-world TTL
        )

    def exchange_public_token(self, *, public_token: str) -> BankLinkHandle:
        self.exchanged_tokens.append(public_token)
        n = next(self._counter)
        return BankLinkHandle(
            plaid_item_id=f"item-fake-{n}-{uuid.uuid4().hex[:8]}",
            access_token=f"access-fake-{n}-{uuid.uuid4().hex[:8]}",
        )


def build_item_login_required_webhook_body(*, plaid_item_id: str) -> dict[str, Any]:
    """FR-43: Plaid's `ITEM` / `ERROR` webhook reporting a re-authentication requirement."""
    return {
        "webhook_type": "ITEM",
        "webhook_code": "ERROR",
        "item_id": plaid_item_id,
        "error": {
            "error_type": "ITEM_ERROR",
            "error_code": "ITEM_LOGIN_REQUIRED",
            "error_message": "the Item's access token is no longer valid",
        },
    }


def build_ach_return_webhook_body(
    *, plaid_item_id: str, settlement_obligation_id: str
) -> dict[str, Any]:
    """FR-6: a Plaid Transfer webhook reporting the ACH debit backing a deposit was returned.

    `ports.py`'s `BankPort` has no `create_transfer`/transfer-reference method -- S2 §5.2 never
    describes `DepositService.initiate()` calling out to Plaid to open a transfer, only posting the
    ledger entries and a `settlement_obligation` row locally. With no provider-side transfer
    reference to correlate against, this payload carries our own `settlement_obligation.id`
    directly as the correlation key, in place of a Plaid `transfer_id` a real transfer-creation call
    would have returned.
    """
    return {
        "webhook_type": "TRANSFER",
        "webhook_code": "TRANSFER_EVENTS_UPDATE",
        "item_id": plaid_item_id,
        "settlement_obligation_id": settlement_obligation_id,
        "event_type": "returned",
    }
