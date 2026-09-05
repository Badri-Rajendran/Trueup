"""Response schemas for `app/controllers/api/identity.py` (S2 §6, OWASP API3).

Explicit allow-lists only -- `plaid_access_token` and any raw entity never reach a response body
(root `CLAUDE.md`, `app/views/` may not import `app/models/`, enforced by `lint-imports`).
"""

from __future__ import annotations

from pydantic import BaseModel


class KycSessionResponse(BaseModel):
    """`POST /api/v1/identity/kyc-sessions` -- the client secret the frontend renders Stripe's
    hosted verification flow with (S2 §6). Never the provider session status; that only ever
    arrives later, via the webhook path."""

    provider_session_id: str
    client_secret: str


class IdentityConfigResponse(BaseModel):
    """`GET /api/v1/identity/config` -- the one provider value a client needs before it can call
    Stripe.js itself (`verifyIdentity(client_secret)`). Safe to expose: a publishable key is
    designed to be embedded in client-side code (`app/config.py`'s own field docstring)."""

    stripe_publishable_key: str


class IdentityStatusResponse(BaseModel):
    """`GET /api/v1/identity/status/<customer_id>` -- both gates, named separately (S2 §3.1's
    conjunction, S2 §7 edge case 2: the surface must show *which* gate is pending, not a generic
    "not approved")."""

    kyc_status: str
    account_approval_status: str
