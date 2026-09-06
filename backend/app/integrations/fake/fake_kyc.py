"""`FakeKycAdapter` — the `KycPort` fake for `tests/contract/` (S2 §8), no network call.

`build_verification_session_webhook_body` constructs a real `identity.verification_session.*`
Stripe webhook body, for testing `KycService`'s webhook path without Stripe.
"""

from __future__ import annotations

import itertools
import uuid
from typing import Any

from app.integrations.ports import KycSessionHandle


class FakeKycAdapter:
    """Implements `KycPort` (structural — no inheritance required)."""

    def __init__(self) -> None:
        self._counter = itertools.count(1)
        self.created_sessions: list[str] = []

    def create_verification_session(self, *, customer_id: str) -> KycSessionHandle:
        provider_session_id = f"vs_fake_{next(self._counter)}_{uuid.uuid4().hex[:8]}"
        self.created_sessions.append(customer_id)
        return KycSessionHandle(
            provider_session_id=provider_session_id,
            client_secret=f"{provider_session_id}_secret_{uuid.uuid4().hex[:8]}",
        )


def build_verification_session_webhook_body(
    *, provider_session_id: str, status: str
) -> dict[str, Any]:
    """A Stripe Identity `identity.verification_session.*` event body, shaped as `construct_event`
    would (S2 §4)."""
    return {
        "id": f"evt_fake_{uuid.uuid4().hex[:8]}",
        "type": f"identity.verification_session.{status}",
        "data": {"object": {"id": provider_session_id, "status": status}},
    }
