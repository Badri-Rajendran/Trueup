"""Account-bootstrap and event-synthesis helpers for S10's services."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from app.models.ledger.account import Account, AccountRole
from app.models.ops.inbound_event import InboundEvent, InboundEventSource

if TYPE_CHECKING:
    from app.services.fees.uow import FeesUnitOfWork


def get_or_create_customer_account(
    uow: FeesUnitOfWork, *, customer_id: uuid.UUID, role: AccountRole
) -> Account:
    statement = select(Account).where(Account.customer_id == customer_id, Account.role == role)
    account = uow.session.execute(statement).scalar_one_or_none()
    if account is None:
        account = Account.create(role, customer_id=customer_id)
        uow.accounts.add(account)
        uow.session.flush()
    return account


def get_or_create_house_account(uow: FeesUnitOfWork, *, role: AccountRole) -> Account:
    statement = select(Account).where(Account.customer_id.is_(None), Account.role == role)
    account = uow.session.execute(statement).scalar_one_or_none()
    if account is None:
        account = Account.create(role)
        uow.accounts.add(account)
        uow.session.flush()
    return account


def record_inbound_event(
    uow: FeesUnitOfWork, *, source: InboundEventSource, kind: str, payload: dict[str, Any]
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


__all__ = ["get_or_create_customer_account", "get_or_create_house_account", "record_inbound_event"]
