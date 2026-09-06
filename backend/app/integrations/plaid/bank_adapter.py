"""`PlaidBankAdapter` (S2 §5.1, FR-4/41/42/43) — the only module that calls the Plaid API.

Webhook verification follows Plaid's JWT scheme: the `Plaid-Verification` header JWT is verified
against a key cached by `kid`, checked for freshness (5-minute replay window), and matched against
the raw body hash.
"""

from __future__ import annotations

import hashlib
import time
from typing import TYPE_CHECKING, Any

import jwt
import plaid
from plaid.api import plaid_api
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.webhook_verification_key_get_request import WebhookVerificationKeyGetRequest

from app.integrations.ports import BankLinkHandle, LinkTokenHandle

if TYPE_CHECKING:
    from collections.abc import Callable

_WEBHOOK_FRESHNESS_SECONDS = 300
"""Plaid's own documented replay window for `Plaid-Verification` JWTs."""


class PlaidCredentialsNotConfiguredError(RuntimeError):
    """Raised rather than silently degrading to a fake when Plaid credentials are absent."""


def _build_client(*, client_id: str, secret: str, environment: str) -> Any:
    """Returns a `plaid_api.PlaidApi`, typed `Any` since `plaid.*` ships no type information."""
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

    def create_link_token(self, *, client_user_id: str) -> LinkTokenHandle:
        response = self._client.link_token_create(
            LinkTokenCreateRequest(
                client_name="Trueup",
                language="en",
                country_codes=[CountryCode("US")],
                user=LinkTokenCreateRequestUser(client_user_id=client_user_id),
                # `auth`: bank account + routing number verification (S2 §5.1's only Plaid product).
                products=[Products("auth")],
            )
        )
        return LinkTokenHandle(link_token=response.link_token, expiration=response.expiration)

    def exchange_public_token(self, *, public_token: str) -> BankLinkHandle:
        response = self._client.item_public_token_exchange(
            ItemPublicTokenExchangeRequest(public_token=public_token)
        )
        return BankLinkHandle(plaid_item_id=response.item_id, access_token=response.access_token)


class PlaidSignatureVerifier:
    """Implements `SignatureVerifier` for Plaid webhooks (S0 §6 step 1). `signature` is the
    `Plaid-Verification` header JWT, not an HMAC digest."""

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
