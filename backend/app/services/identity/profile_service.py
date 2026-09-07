"""Customer profile read/update (ADR 27). Self-scoped only -- the controller resolves the
customer from the session; this service is never handed a caller-chosen customer_id to trust.
`display_name`/`phone`/`mailing_address` are never passed to a logger call here or anywhere else
(ADR 27's log-redaction rule)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.core.errors import NotFoundError

if TYPE_CHECKING:
    import uuid
    from collections.abc import Mapping

    from app.models.identity.customer import Customer
    from app.services.identity.uow import IdentityUnitOfWork

_PROFILE_FIELDS = ("display_name", "phone", "mailing_address")


@dataclass(frozen=True)
class ProfileUpdate:
    """Only the fields the caller actually supplied (ADR 27's partial-update semantics), keyed by
    column name; a value of `None` means "clear this field," a key's absence means "leave it
    untouched." Build from a validated request's `model_fields_set`, never from every declared
    field, or an omitted field would be silently overwritten with `None`."""

    fields: Mapping[str, str | None] = field(default_factory=dict)

    def is_set(self, name: str) -> bool:
        return name in self.fields


class ProfileService:
    """Reads and partially updates the profile fields owned by `/api/v1/profile` (ADR 27)."""

    def __init__(self, uow: IdentityUnitOfWork) -> None:
        self._uow = uow

    def get(self, customer_id: uuid.UUID) -> Customer:
        customer = self._uow.customers.get_by_id(customer_id)
        if customer is None:  # pragma: no cover - defensive; an authenticated session always
            # corresponds to a persisted customer row.
            raise NotFoundError("customer not found")
        return customer

    def apply_update(self, customer: Customer, update: ProfileUpdate) -> None:
        """Mutates an already-loaded `Customer` in place -- never re-queries. A post-commit
        re-query would run in a fresh transaction with no `app.customer_id` `SET LOCAL` in
        effect (that setting does not outlive the transaction it was set in), making the row
        invisible to RLS; `kyc_overrides.py` avoids the same trap by building its response from
        the object it already holds, not a second lookup."""
        for name in _PROFILE_FIELDS:
            if update.is_set(name):
                setattr(customer, name, update.fields[name])
