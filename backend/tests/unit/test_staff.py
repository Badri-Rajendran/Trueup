"""`Staff` model invariants: `AuthPrincipal` shape and `role` enum, no database (S0 §7.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SQLAlchemyEnum

from app.models.identity import AuthPrincipal
from app.models.identity.staff import Staff, StaffRole


def _staff(role: StaffRole = StaffRole.adviser) -> Staff:
    return Staff(
        id=uuid.uuid4(),
        email="adviser@trueup.test",
        password_hash="argon2-hash",
        role=role,
    )


def test_staff_satisfies_the_auth_principal_protocol() -> None:
    assert isinstance(_staff(), AuthPrincipal)


def test_role_column_enforces_exactly_the_adviser_admin_value_set() -> None:
    column_type = Staff.__table__.c.role.type
    assert isinstance(column_type, SQLAlchemyEnum)
    assert set(column_type.enums) == {"adviser", "admin"}


def test_role_is_usable_as_a_plain_string_not_a_bare_enum_repr() -> None:
    """Regression guard: `StaffRole` must compare/format as a plain string, or role checks
    silently fail across `core/security.py` and the auth controller."""
    staff = _staff(StaffRole.adviser)

    assert staff.role == "adviser"
    assert staff.role in ("adviser", "admin")
    assert str(staff.role) == "adviser"
    assert f"{staff.role}" == "adviser"


def test_admin_role_also_compares_as_a_plain_string() -> None:
    staff = _staff(StaffRole.admin)
    assert staff.role == "admin"
    assert staff.role in ("adviser", "admin")


def test_totp_secret_defaults_to_unenrolled() -> None:
    staff = _staff()
    assert staff.totp_secret_encrypted is None


def test_get_id_returns_the_string_primary_key() -> None:
    staff_id = uuid.uuid4()
    staff = Staff(id=staff_id, email="a@b.test", password_hash="x", role=StaffRole.admin)
    assert staff.get_id() == str(staff_id)
