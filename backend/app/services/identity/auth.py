"""Stateless authentication helpers (S0 §7.1/§7.2): password hashing, principal lookup, TOTP.

Principal lookup goes through `IdentityUnitOfWork.customers`/`.staff` — the repositories
`app/models/identity/repository.py` already defines — rather than re-querying `Customer`/`Staff`
directly here, so there is exactly one place that knows how to read either table (DRY,
`backend/CLAUDE.md`).
"""

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

# A fixed, valid Argon2id hash of a password nobody can log in with. `authenticate()` verifies
# against this when no principal matches the given email, so an unknown-email login costs exactly
# the same Argon2 work as a wrong-password one — otherwise the *unknown-email* branch returns
# early with no hash to verify, and its faster response time becomes an account-enumeration
# oracle (OWASP A07 / API2).
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
    """Callers that fetch and then mutate the result inside their own `UnitOfWork` block (e.g.
    `mfa_enroll` fetching `staff` then setting `staff.totp_secret_encrypted`) depend on the
    returned object staying tracked by `uow.session` so `uow.commit()` actually persists the
    write -- do not detach it here. `load_user()` is the one caller that returns this object
    *across* its own `UnitOfWork`'s exit; it detaches the object itself, at its own call site,
    precisely because every other caller must not have that done on its behalf."""
    parsed_id = user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(user_id)
    customer = uow.customers.get_by_id(parsed_id)
    if customer is not None:
        return customer
    return uow.staff.get_by_id(parsed_id)


def authenticate(uow: IdentityUnitOfWork, email: str, password: str) -> AuthPrincipal | None:
    """Look up a principal by email and verify the password.

    Returns `None` for both "no such email" and "wrong password" — the auth controller must raise
    the same error for both (S0 §7 login test list: a prober cannot distinguish the two), and this
    is also where that indistinguishability is made true at the timing level, not just the
    response-body level (see `_DUMMY_HASH`).
    """
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
