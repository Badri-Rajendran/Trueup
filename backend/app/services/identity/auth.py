"""Stateless authentication helpers (S0 §7.1/§7.2): password hashing, principal lookup, TOTP."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

if TYPE_CHECKING:
    from app.models.identity import AuthPrincipal
    from app.services.identity.uow import IdentityUnitOfWork

ph = PasswordHasher()

_TOTP_ISSUER = "Trueup"

# Dummy hash verified on unknown-email login to prevent timing-based account enumeration (OWASP A07).
_DUMMY_HASH = ph.hash("trueup-timing-safety-dummy-password-never-a-real-account")


def hash_password(password: str) -> str:
    return ph.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        ph.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False


def find_principal_by_email(uow: IdentityUnitOfWork, email: str) -> AuthPrincipal | None:
    customer = uow.customers.get_by_email(email)
    if customer is not None:
        return customer
    return uow.staff.get_by_email(email)


def find_principal_by_id(uow: IdentityUnitOfWork, user_id: uuid.UUID | str) -> AuthPrincipal | None:
    """Returns the object still tracked by `uow.session` — do not detach it here."""
    parsed_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)
    customer = uow.customers.get_by_id(parsed_id)
    if customer is not None:
        return customer
    return uow.staff.get_by_id(parsed_id)


def authenticate(uow: IdentityUnitOfWork, email: str, password: str) -> AuthPrincipal | None:
    """Returns `None` for both "no such email" and "wrong password" (indistinguishable, S0 §7)."""
    principal = find_principal_by_email(uow, email)
    if principal is None:
        verify_password(_DUMMY_HASH, password)
        return None
    if not verify_password(principal.password_hash, password):
        return None
    return principal


def generate_totp_secret() -> str:
    return pyotp.random_base32()


def totp_provisioning_uri(secret: str, email: str) -> str:
    """The `otpauth://` URI an authenticator app scans during `/mfa/enroll` (S0 §7.2)."""
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=_TOTP_ISSUER)


def verify_totp(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code)
