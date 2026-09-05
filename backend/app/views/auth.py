"""Response schemas for `app/controllers/api/auth.py` (S0 §8, OWASP API3).

Explicit allow-lists only — never a raw `Customer`/`Staff` entity (`app/views/` may not import
`app/models/`, enforced by `lint-imports`'s `views-are-not-entities` contract).
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- Pydantic resolves field annotations at class-build time, not just
from datetime import datetime  # noqa: TC003 -- for static type checking; both must be real imports.

from pydantic import BaseModel, ConfigDict


class RegisterResponse(BaseModel):
    """`POST /api/v1/auth/register` (customer only, S0 §7.2)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    created_at: datetime


class AuthResponse(BaseModel):
    """A fully-authenticated session (customer login, or staff after `/mfa/verify`)."""

    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    email: str
    role: str
    csrf_token: str
    mfa_pending: bool = False


class MfaPendingResponse(BaseModel):
    """Staff login landed in the partial/pending-MFA state (S0 §7.1) — a second `/mfa/verify`
    call, carrying this `csrf_token`, is required before the session is fully authenticated."""

    status: str
    csrf_token: str
    mfa_pending: bool = True


class MfaEnrollResponse(BaseModel):
    """`POST /api/v1/auth/mfa/enroll` (staff only) — the secret is not active until confirmed by
    `/mfa/verify` (S0 §7.2's two-step enrollment)."""

    secret: str
    provisioning_uri: str


class LogoutResponse(BaseModel):
    status: str
