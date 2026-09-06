"""`BankLinkService` (S2 §3.3/§5.1, FR-4/41/42/43)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.models.identity.bank_link import BankLink, BankLinkStatus

if TYPE_CHECKING:
    import uuid

    from app.integrations.ports import BankPort
    from app.services.identity.uow import IdentityUnitOfWork


class BankLinkNotFoundError(RuntimeError):
    """Raised when a webhook names a `plaid_item_id` this system has no `bank_link` row for."""


class BankPortNotConfiguredError(RuntimeError):
    """Raised when `create_link` is called on a `BankLinkService` built without a `BankPort` --
    the webhook path (`apply_item_login_required` only) never needs one, so callers on that path
    may omit it entirely."""


class BankLinkService:
    def __init__(self, uow: IdentityUnitOfWork, *, bank_port: BankPort | None = None) -> None:
        self._uow = uow
        self._bank_port = bank_port

    def create_link(self, customer_id: uuid.UUID, *, plaid_public_token: str) -> BankLink:
        """S2 §5.1: exchange the public token, then supersede any prior active/`requires_reauth`
        link in the same transaction that activates the new one (FR-42)."""
        if self._bank_port is None:
            raise BankPortNotConfiguredError(
                "create_link requires a BankPort; this BankLinkService was built without one"
            )
        handle = self._bank_port.exchange_public_token(public_token=plaid_public_token)
        new_link = BankLink(
            customer_id=customer_id,
            plaid_item_id=handle.plaid_item_id,
            plaid_access_token=handle.access_token,
            status=BankLinkStatus.ACTIVE,
        )
        self._uow.bank_links.supersede_and_activate(new_link)
        return new_link

    def apply_item_login_required(self, plaid_item_id: str) -> None:
        """FR-43: a Plaid webhook reporting `ITEM_LOGIN_REQUIRED` transitions the named link to
        `requires_reauth`. A stale webhook for an already-`superseded` link is ignored -- the
        customer has already re-linked, so there is nothing left to flag."""
        link = self._uow.bank_links.get_by_plaid_item_id(plaid_item_id)
        if link is None:
            raise BankLinkNotFoundError(f"no bank_link found for plaid_item_id={plaid_item_id!r}")
        if link.status is BankLinkStatus.ACTIVE:
            link.status = BankLinkStatus.REQUIRES_REAUTH
