"""`StripeKycAdapter` (S2 §5.1, ADR 9) — the only module that calls the Stripe Identity API.
`services/` depends on `KycPort`, never this class directly (S0 §3); ADR 9's verdict-status mapping
lives in `app.services.identity.kyc_service` instead.
"""

from __future__ import annotations

import stripe

from app.integrations.ports import KycSessionHandle


class StripeCredentialsNotConfiguredError(RuntimeError):
    """Raised rather than silently degrading to a fake when Stripe credentials are absent."""


class StripeKycAdapter:
    """Implements `KycPort` (structural — no inheritance required)."""

    def __init__(self, *, api_key: str) -> None:
        if not api_key:
            raise StripeCredentialsNotConfiguredError(
                "Stripe API key is required to create a live verification session"
            )
        self._api_key = api_key

    def create_verification_session(self, *, customer_id: str) -> KycSessionHandle:
        session = stripe.identity.VerificationSession.create(
            type="document",
            metadata={"customer_id": customer_id},
            api_key=self._api_key,
        )
        if not session.client_secret:
            raise RuntimeError(
                "Stripe Identity did not return a client_secret for the created session"
            )
        return KycSessionHandle(
            provider_session_id=session.id, client_secret=session.client_secret
        )


class StripeIdentitySignatureVerifier:
    """Implements `SignatureVerifier` for Stripe Identity webhooks (S0 §6 step 1, ADR 9)."""

    def __init__(self, *, webhook_secret: str) -> None:
        if not webhook_secret:
            raise StripeCredentialsNotConfiguredError(
                "Stripe Identity webhook secret is required to verify inbound webhooks"
            )
        self._webhook_secret = webhook_secret

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        if signature is None:
            return False
        try:
            stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except (stripe.SignatureVerificationError, ValueError):
            return False
        return True
