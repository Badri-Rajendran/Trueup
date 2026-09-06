"""`FakeBankAdapter` — the `BankPort` fake for `tests/contract/` (S2 §8), no network call.

`build_*_webhook_body` helpers construct the real Plaid webhook JSON for `ITEM_LOGIN_REQUIRED`
(FR-43) and a bounced ACH return (FR-6), for testing the webhook path without Plaid.
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
    Carries our own `settlement_obligation.id` as the correlation key (no Plaid transfer_id, S2 §5.2)."""
    return {
        "webhook_type": "TRANSFER",
        "webhook_code": "TRANSFER_EVENTS_UPDATE",
        "item_id": plaid_item_id,
        "settlement_obligation_id": settlement_obligation_id,
        "event_type": "returned",
    }
