"""`CreateStaffJob` against real PostgreSQL -- the only code path that provisions a `staff` row.

Covers the two properties that matter for a credential-creating command: the row it writes can
actually authenticate (argon2 hash verifies, no TOTP secret so first login enrolls), and a re-run
refuses rather than silently resetting an existing account's password.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.jobs.create_staff import CreateStaffJob, EmailAlreadyRegisteredError
from app.models.identity.customer import Customer
from app.models.identity.staff import Staff, StaffRole
from app.services.identity.auth import hash_password, verify_password

EMAIL = "ops-adviser@trueup.example"
PASSWORD = "a-sufficiently-long-operator-password"


@pytest.fixture
def cleanup_staff(owner_engine: Engine):
    # `checkfirst=True` and no teardown drop: `customer`/`staff` are shared identity tables other
    # integration files (e.g. `test_identity_rls.py`) also create and may hold open FKs into, so
    # this fixture creates them if absent and cleans up only its own rows.
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    Staff.__table__.create(bind=owner_engine, checkfirst=True)
    yield
    session = Session(bind=owner_engine)
    session.query(Staff).filter(Staff.email == EMAIL).delete()
    session.query(Customer).filter(Customer.email == EMAIL).delete()
    session.commit()
    session.close()


def _fetch_staff(owner_engine: Engine, email: str) -> Staff | None:
    session = Session(bind=owner_engine, expire_on_commit=False)
    row = session.query(Staff).filter_by(email=email).first()
    session.close()
    return row


def test_creates_a_staff_row_that_can_authenticate(
    owner_engine: Engine, cleanup_staff: None
) -> None:
    result = CreateStaffJob().run(email=EMAIL, password=PASSWORD, role=StaffRole.adviser)

    assert result.email == EMAIL
    assert result.role is StaffRole.adviser

    stored = _fetch_staff(owner_engine, EMAIL)
    assert stored is not None
    assert stored.id == result.staff_id
    assert stored.role is StaffRole.adviser
    # The password must actually verify -- a row whose hash does not match is worse than no row.
    assert verify_password(stored.password_hash, PASSWORD) is True
    assert stored.password_hash != PASSWORD
    # No secret yet: `/auth/mfa/enroll`'s first-time path enrolls the authenticator on first login.
    assert stored.totp_secret_encrypted is None


def test_email_is_normalized_to_lowercase(owner_engine: Engine, cleanup_staff: None) -> None:
    """Login looks the email up verbatim, so a capitalized provisioning argument must not create
    an account whose owner can never type their way into it."""
    CreateStaffJob().run(
        email="  OPS-Adviser@Trueup.Example  ", password=PASSWORD, role=StaffRole.admin
    )

    assert _fetch_staff(owner_engine, EMAIL) is not None


def test_rerunning_for_an_existing_staff_email_refuses(cleanup_staff: None) -> None:
    """Must not silently reset a live account's password -- the classic accidental-rerun footgun."""
    CreateStaffJob().run(email=EMAIL, password=PASSWORD, role=StaffRole.adviser)

    with pytest.raises(EmailAlreadyRegisteredError, match="already registered as staff"):
        CreateStaffJob().run(email=EMAIL, password="a-different-password", role=StaffRole.admin)


def test_refuses_an_email_already_registered_as_a_customer(
    owner_engine: Engine, cleanup_staff: None
) -> None:
    """`find_principal_by_email` resolves customers first, so such a staff row could never
    log in."""
    session = Session(bind=owner_engine)
    session.add(Customer(email=EMAIL, password_hash=hash_password(PASSWORD)))
    session.commit()
    session.close()

    with pytest.raises(EmailAlreadyRegisteredError, match="already registered as a customer"):
        CreateStaffJob().run(email=EMAIL, password=PASSWORD, role=StaffRole.adviser)


@pytest.mark.parametrize(("email", "password"), [("", PASSWORD), ("   ", PASSWORD), (EMAIL, "")])
def test_rejects_empty_email_or_password(email: str, password: str) -> None:
    with pytest.raises(ValueError):
        CreateStaffJob().run(email=email, password=password, role=StaffRole.adviser)
