"""`PlaidBankAdapter` (S2 §5.1, FR-4/41/42/43) — the only module that calls the Plaid API.

`services/` depends on `BankPort` (`app/integrations/ports.py`), never this class directly (S0 §3's
dependency rule). Webhook verification follows Plaid's documented JWT scheme: each webhook carries a
`Plaid-Verification` header holding a JWT signed ES256 by a key Plaid rotates, identified by the
JWT's own `kid`; the verifier fetches that key (cached, since Plaid's own guidance is to cache by
`kid` rather than call the key-fetch endpoint per webhook), verifies the signature, checks the claim
is fresh (issued within the last five minutes — replay defence), and compares the claimed body hash
against the actual raw request body.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

import jwt
import plaid
from plaid.api import plaid_api
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.webhook_verification_key_get_request import WebhookVerificationKeyGetRequest

from app.integrations.ports import BankLinkHandle

if TYPE_CHECKING:
    from collections.abc import Callable

_WEBHOOK_FRESHNESS_SECONDS = 300
"""Plaid's own documented replay window for `Plaid-Verification` JWTs."""


class PlaidCredentialsNotConfiguredError(RuntimeError):
    """Raised rather than silently degrading to a fake when Plaid credentials are absent."""


def _build_client(*, client_id: str, secret: str, environment: str) -> Any:
    """Returns a `plaid_api.PlaidApi` -- typed `Any` since `plaid.*` ships no type information
    (`pyproject.toml`'s mypy override) and `disallow_any_unimported` forbids naming its types
    directly in an annotation."""
    host = {
        "sandbox": plaid.Environment.Sandbox,
        "production": plaid.Environment.Production,
    }.get(environment, plaid.Environment.Sandbox)
    configuration = plaid.Configuration(
        host=host,
        api_key={"clientId": client_id, "secret": secret},
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


class PlaidBankAdapter:
    """Implements `BankPort` (structural — no inheritance required)."""

    def __init__(self, *, client_id: str, secret: str, environment: str = "sandbox") -> None:
        if not client_id or not secret:
            raise PlaidCredentialsNotConfiguredError(
                "Plaid client_id/secret are required to exchange a live public token"
            )
        self._client = _build_client(client_id=client_id, secret=secret, environment=environment)

    def exchange_public_token(self, *, public_token: str) -> BankLinkHandle:
        response = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return BankLinkHandle(plaid_item_id=response.item_id, access_token=response.access_token)


class PlaidSignatureVerifier:
    """Implements `app.services.intake.event_intake.SignatureVerifier` for Plaid webhooks (S0 §6
    step 1). `signature` is the `Plaid-Verification` header value -- a JWT, not an HMAC digest."""

    def __init__(
        self,
        *,
        client_id: str,
        secret: str,
        environment: str = "sandbox",
        now: Callable[[], float] = time.time,
    ) -> None:
        if not client_id or not secret:
            raise PlaidCredentialsNotConfiguredError(
                "Plaid client_id/secret are required to verify inbound webhooks"
            )
        self._client = _build_client(client_id=client_id, secret=secret, environment=environment)
        self._now = now
        self._key_cache: dict[str, Any] = {}

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        if signature is None:
            return False
        try:
            header = jwt.get_unverified_header(signature)
            kid = header["kid"]
            key = self._get_key(kid)
            claims = jwt.decode(signature, key=key, algorithms=["ES256"])
        except (jwt.InvalidTokenError, KeyError, ValueError):
            return False

        issued_at = claims.get("iat")
        if not isinstance(issued_at, int | float):
            return False
        if self._now() - issued_at > _WEBHOOK_FRESHNESS_SECONDS:
            return False

        expected_hash = hashlib.sha256(payload).hexdigest()
        return claims.get("request_body_sha256") == expected_hash

    def _get_key(self, kid: str) -> Any:
        if kid not in self._key_cache:
            response = self._client.webhook_verification_key_get(
                WebhookVerificationKeyGetRequest(key_id=kid)
            )
            self._key_cache[kid] = jwt.algorithms.ECAlgorithm.from_jwk(response.key.to_dict())
        return self._key_cache[kid]
