"""`Customer` model invariants (S2 §3.1 / S0 §7.2): the `AuthPrincipal` shape and the enum columns.

No database — see `test_staff.py`'s module docstring for why the enum-domain assertion is made
against SQLAlchemy's column metadata rather than a live insert.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Enum as SQLAlchemyEnum

from app.models.identity import AuthPrincipal
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus


def _customer(**overrides: object) -> Customer:
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "email": "customer@trueup.test",
        "password_hash": "argon2-hash",
    }
    defaults.update(overrides)
    return Customer(**defaults)  # type: ignore[arg-type]


def test_customer_satisfies_the_auth_principal_protocol() -> None:
    assert isinstance(_customer(), AuthPrincipal)


def test_role_is_the_constant_string_customer() -> None:
    customer = _customer()
    assert customer.role == "customer"


def test_role_has_no_setter_it_is_always_implicitly_customer() -> None:
    """S0 §7.2: `customer` has no `role` column; its role is always implicitly `'customer'`."""
    customer = _customer()
    with __import__("pytest").raises(AttributeError):
        customer.role = "adviser"  # type: ignore[misc]


def test_kyc_status_column_enforces_its_declared_value_set() -> None:
    column_type = Customer.__table__.c.kyc_status.type
    assert isinstance(column_type, SQLAlchemyEnum)
    assert set(column_type.enums) == {"pending", "approved", "rejected"}


def test_account_approval_status_column_enforces_its_declared_value_set() -> None:
    column_type = Customer.__table__.c.account_approval_status.type
    assert isinstance(column_type, SQLAlchemyEnum)
    assert set(column_type.enums) == {"pending", "approved", "rejected"}


def test_kyc_status_and_approval_status_default_to_pending() -> None:
    """`default=` is a client-side INSERT-time default (S0 §5) — it applies when the row is
    flushed, not on bare construction, so this asserts the column's configured default rather
    than an unflushed instance's attribute.
    """
    assert Customer.__table__.c.kyc_status.default.arg == KycStatus.pending
    assert Customer.__table__.c.account_approval_status.default.arg == AccountApprovalStatus.pending


def test_get_id_returns_the_string_primary_key() -> None:
    customer_id = uuid.uuid4()
    customer = _customer(id=customer_id)
    assert customer.get_id() == str(customer_id)
