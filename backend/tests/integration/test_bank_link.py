"""S2 §3.3/FR-42 -- `bank_link`'s partial unique index (real Postgres constraint, not an
application check) and its supersede-on-relink behaviour, plus tenant isolation."""

from __future__ import annotations

import base64
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.core.crypto import reset_cipher, set_cipher
from app.core.uow import SessionRole, UnitOfWork
from app.extensions import DbRole, dispose_engines, init_engines
from app.integrations.crypto.local_cipher import LocalDevCipher
from app.models.identity.bank_link import BankLink, BankLinkStatus, SqlBankLinkRepository
from app.models.identity.customer import Customer

pytestmark = pytest.mark.usefixtures("_bank_link_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    set_cipher(LocalDevCipher(base64.b64encode(b"0" * 32).decode()))
    yield None
    dispose_engines()
    reset_cipher()


@pytest.fixture
def _bank_link_tables(owner_engine: Engine) -> Iterator[None]:
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    BankLink.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text(f'DROP TABLE IF EXISTS "{BankLink.__table__.name}" CASCADE'))
        connection.execute(text(f'DROP TABLE IF EXISTS "{Customer.__table__.name}" CASCADE'))


def _insert_customer(db_committing) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    db_committing.add(customer)
    db_committing.flush()
    return customer.id


def _link(customer_id: uuid.UUID, *, status: BankLinkStatus = BankLinkStatus.ACTIVE) -> BankLink:
    return BankLink(
        customer_id=customer_id,
        plaid_item_id=f"item-{uuid.uuid4()}",
        plaid_access_token="access-sandbox-token",
        status=status,
    )


def test_partial_unique_index_rejects_a_second_concurrent_active_link(db_committing) -> None:
    customer_id = _insert_customer(db_committing)
    db_committing.add(_link(customer_id))
    db_committing.commit()

    db_committing.add(_link(customer_id))
    with pytest.raises(IntegrityError):
        db_committing.commit()


def test_a_superseded_link_does_not_block_a_new_active_link(db_committing) -> None:
    customer_id = _insert_customer(db_committing)
    db_committing.add(_link(customer_id, status=BankLinkStatus.SUPERSEDED))
    db_committing.commit()

    db_committing.add(_link(customer_id, status=BankLinkStatus.ACTIVE))
    db_committing.commit()  # does not raise


def test_supersede_and_activate_transitions_the_prior_active_and_reauth_links(
    db_committing,
) -> None:
    customer_id = _insert_customer(db_committing)
    old_active = _link(customer_id, status=BankLinkStatus.ACTIVE)
    db_committing.add(old_active)
    db_committing.commit()

    old_active.status = BankLinkStatus.REQUIRES_REAUTH
    db_committing.commit()

    class _Uow:
        def __init__(self, session):
            self.session = session
            self.role = SessionRole.ADMIN
            self.customer_id = None

    repo = SqlBankLinkRepository(_Uow(db_committing))
    new_link = _link(customer_id, status=BankLinkStatus.ACTIVE)
    repo.supersede_and_activate(new_link)
    db_committing.commit()

    db_committing.refresh(old_active)
    assert old_active.status is BankLinkStatus.SUPERSEDED
    active = repo.active_for_customer(customer_id)
    assert active is not None
    assert active.id == new_link.id


def test_customer_session_cannot_see_another_customers_bank_link(db_committing) -> None:
    customer_a = _insert_customer(db_committing)
    customer_b = _insert_customer(db_committing)
    db_committing.add_all([_link(customer_a), _link(customer_b)])
    db_committing.commit()

    with UnitOfWork(customer_id=customer_a, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow:
        visible = {row.customer_id for row in uow.session.execute(select(BankLink)).scalars()}
    assert visible == {customer_a}
