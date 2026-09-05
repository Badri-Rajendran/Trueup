"""Account-bootstrap and event-synthesis helpers shared by S5's three services.

`get_or_create_customer_account`/`get_or_create_house_account` follow
`DepositService._account_for`'s exact precedent (S2): lazily create a ledger account the first
time a customer (or the house) needs one, rather than requiring some earlier step to have done it.
`DIVIDEND_INCOME` is created house-wide (`customer_id=None`) per `account.py`'s own module
docstring ("null only for house accounts (`fees_expense`, `dividend_income`)") -- an already-
decided S1 convention this module conforms to, not one it introduces.

`record_inbound_event` follows `DepositService._record_inbound_event`'s exact precedent: every
`journal_entry.source_event_id` must reference a real `inbound_event` row, and
`InboundEventDispatcher.handle()` only forwards a handler the raw payload, not the id of the
`inbound_event` that triggered it (`app/services/intake/dispatch.py`) -- so each posting synthesizes
its own audit-trail row here, exactly as S2 already does for deposits/withdrawals.
"""

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
    """For roles an earlier step is already responsible for creating (`cash`, matching
    `DepositService._account_for`'s strict branch) -- a missing row here is a real invariant
    violation (account approval should have created it), never a lazy-bootstrap opportunity."""
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
