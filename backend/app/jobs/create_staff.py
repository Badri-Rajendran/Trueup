"""Operator command that provisions a `staff` row -- the one principal this codebase had no way
to create.

`POST /api/v1/auth/register` (`app/controllers/api/auth.py`) hardcodes `Customer(...)` and there is
deliberately no staff self-registration route: staff are provisioned by an operator, never by a
visitor. But nothing else called `uow.staff.add()` either, so `staff` stayed empty in every
environment, and with it every route behind `@requires_role('adviser', 'admin')` -- the four admin
screens (`/admin/breaks`, `/admin/customers`, and their detail routes) were unreachable by anybody.
This closes that gap without opening a public registration surface.

`flask jobs create-staff --email ... --role ...` (`app/jobs/__init__.py`), prompting for the
password rather than taking it as an argument so it never lands in shell history, a process list,
or a CI log. Reads whatever `DATABASE_URL*` the environment already has configured, so the same
command provisions dev, staging, or the deployed instance.

The new account has **no TOTP secret**. That is intended, not an omission: `Staff` login is
MFA-gated (S0 §7.1), and `POST /auth/mfa/enroll`'s first-time path enrolls it on first login via
`pending_mfa_user_id`. Minting a secret here would mean transporting it to the operator out of
band, which is strictly worse than enrolling in the authenticator on first use.

Not a `ScheduledJob` (`app/jobs/base.py`) -- that abstraction is for a market-date-anchored
recurring cadence (S0 §9/ADR 13), and a required `--market-date` plus a `job_run` row would be a
category error for a one-off administrative bootstrap. Follows `seed-reference-data` and
`outbox-worker`, the two commands in `app/jobs/__init__.py` that are not `ScheduledJob`s either.
"""

from __future__ import annotations

import uuid  # noqa: TC003 -- dataclass field annotation, resolved at class-build time
from dataclasses import dataclass

from app.core.db import DbRole
from app.core.logging import get_logger
from app.core.uow import SessionRole
from app.models.identity.staff import Staff, StaffRole
from app.services.identity.auth import hash_password
from app.services.identity.uow import IdentityUnitOfWork

logger = get_logger(__name__)


class EmailAlreadyRegisteredError(RuntimeError):
    """The email already belongs to a `Customer` or a `Staff` row."""


@dataclass(frozen=True)
class CreateStaffResult:
    staff_id: uuid.UUID
    email: str
    role: StaffRole


class CreateStaffJob:
    """Provisions one `staff` row. Not idempotent by design -- re-running for an existing email
    raises rather than silently resetting that account's password, which is what an accidental
    re-run of a credential-creating command must never do."""

    def run(self, *, email: str, password: str, role: StaffRole) -> CreateStaffResult:
        normalized_email = email.strip().lower()
        if not normalized_email:
            raise ValueError("email is required")
        if not password:
            raise ValueError("password is required")

        with IdentityUnitOfWork(
            customer_id=None, role=SessionRole.ADMIN, db_role=DbRole.APP
        ) as uow:
            # Both tables, not just `staff`: `find_principal_by_email`
            # (`app/services/identity/auth.py`) resolves customers first, so a staff row sharing a
            # customer's email would be permanently shadowed at login -- an account that exists but
            # can never authenticate. Refuse instead of creating one.
            if uow.customers.get_by_email(normalized_email) is not None:
                raise EmailAlreadyRegisteredError(
                    f"{normalized_email} is already registered as a customer"
                )
            if uow.staff.get_by_email(normalized_email) is not None:
                raise EmailAlreadyRegisteredError(
                    f"{normalized_email} is already registered as staff"
                )

            staff = Staff(
                email=normalized_email,
                password_hash=hash_password(password),
                role=role,
            )
            uow.staff.add(staff)
            uow.commit()
            result = CreateStaffResult(staff_id=staff.id, email=staff.email, role=staff.role)

        # Email and role only -- never the password or its hash (root CLAUDE.md: secrets and PII
        # stay out of logs).
        logger.info(
            "create_staff.completed",
            staff_id=str(result.staff_id),
            email=result.email,
            role=result.role.value,
        )
        return result
