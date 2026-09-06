"""Account-bootstrap and event-synthesis helpers shared by S5's three services."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.ledger.account import Account, AccountRole
from app.models.ops.inbound_event import InboundEvent, InboundEventSource

if TYPE_CHECKING:
    from app.services.lots.uow import LotsUnitOfWork


def get_or_create_customer_account(
    uow: LotsUnitOfWork,
    *,
    customer_id: uuid.UUID,
    role: AccountRole,
    security_id: uuid.UUID | None = None,
) -> Account:
    statement = select(Account).where(Account.customer_id == customer_id, Account.role == role)
    if security_id is not None:
        statement = statement.where(Account.security_id == security_id)
    account = uow.session.execute(statement).scalar_one_or_none()
    if account is None:
        account = Account.create(role, customer_id=customer_id, security_id=security_id)
        uow.accounts.add(account)
        uow.session.flush()
    return account


def require_customer_account(
    uow: LotsUnitOfWork, *, customer_id: uuid.UUID, role: AccountRole
) -> Account:
    """For roles an earlier step already creates (`cash`); a missing row is an invariant violation."""
    account = uow.session.execute(
        select(Account).where(Account.customer_id == customer_id, Account.role == role)
    ).scalar_one_or_none()
    if account is None:
        raise RuntimeError(
            f"customer {customer_id!r} has no {role.value} account -- account approval should "
            "have created it (S2's AccountApprovalService)"
        )
    return account


def get_or_create_house_account(uow: LotsUnitOfWork, *, role: AccountRole) -> Account:
    statement = select(Account).where(Account.customer_id.is_(None), Account.role == role)
    account = uow.session.execute(statement).scalar_one_or_none()
    if account is None:
        account = Account.create(role)
        uow.accounts.add(account)
        uow.session.flush()
    return account


def record_inbound_event(
    uow: LotsUnitOfWork, *, source: InboundEventSource, kind: str, payload: dict[str, Any]
) -> InboundEvent:
    event = InboundEvent(
        source=source,
        source_event_id=f"{kind}:{uuid.uuid4()}",
        payload=payload,
        signature_verified=True,
    )
    uow.inbound_events.add(event)
    uow.session.flush()
    return event


__all__ = [
    "get_or_create_customer_account",
    "get_or_create_house_account",
    "record_inbound_event",
]
