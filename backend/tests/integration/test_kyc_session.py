"""S2 §3.2/§4 -- `kyc_session`'s single-transition trigger and tenant isolation, mirroring
`tests/integration/test_settlement_obligation.py`'s split between an application-level guard and
its database backstop."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from app.config import Settings
from app.core.uow import SessionRole, UnitOfWork
from app.extensions import DbRole, dispose_engines, init_engines
from app.models.identity.customer import Customer
from app.models.identity.kyc_session import (
    KycSession,
    KycSessionAlreadyResolvedError,
    KycSessionStatus,
    SqlKycSessionRepository,
)

pytestmark = pytest.mark.usefixtures("_kyc_session_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def _kyc_session_tables(owner_engine: Engine) -> Iterator[None]:
    Customer.__table__.create(bind=owner_engine, checkfirst=True)
    KycSession.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        connection.execute(text(f'DROP TABLE IF EXISTS "{KycSession.__table__.name}" CASCADE'))
        connection.execute(text(f'DROP TABLE IF EXISTS "{Customer.__table__.name}" CASCADE'))


def _insert_customer(db_committing) -> uuid.UUID:
    customer = Customer(email=f"{uuid.uuid4()}@trueup.test", password_hash="hash")
    db_committing.add(customer)
    db_committing.flush()
    return customer.id


def test_repository_rejects_a_second_transition_on_an_already_terminal_session(
    db_committing,
) -> None:
    customer_id = _insert_customer(db_committing)
    session_row = KycSession(
        customer_id=customer_id,
        provider_session_id=f"vs_{uuid.uuid4()}",
        status=KycSessionStatus.PENDING,
        attempt_number=1,
    )
    db_committing.add(session_row)
    db_committing.commit()

    SqlKycSessionRepository.resolve(
        session_row, status=KycSessionStatus.APPROVED, resolved_at=datetime.now(UTC)
    )
    db_committing.commit()

    with pytest.raises(KycSessionAlreadyResolvedError):
        SqlKycSessionRepository.resolve(
            session_row, status=KycSessionStatus.REJECTED, resolved_at=datetime.now(UTC)
        )


def test_database_trigger_rejects_a_second_transition_even_bypassing_the_repository(
    db_committing,
) -> None:
    customer_id = _insert_customer(db_committing)
    session_row = KycSession(
        customer_id=customer_id,
        provider_session_id=f"vs_{uuid.uuid4()}",
        status=KycSessionStatus.PENDING,
        attempt_number=1,
    )
    db_committing.add(session_row)
    db_committing.commit()

    session_row.status = KycSessionStatus.APPROVED
    session_row.resolved_at = datetime.now(UTC)
    db_committing.commit()

    session_row.status = KycSessionStatus.REJECTED
    with pytest.raises(DBAPIError):
        db_committing.commit()


def test_customer_session_cannot_see_another_customers_kyc_session(db_committing) -> None:
    customer_a = _insert_customer(db_committing)
    customer_b = _insert_customer(db_committing)
    db_committing.add_all(
        [
            KycSession(
                customer_id=customer_a,
                provider_session_id=f"vs_{uuid.uuid4()}",
                status=KycSessionStatus.PENDING,
                attempt_number=1,
            ),
            KycSession(
                customer_id=customer_b,
                provider_session_id=f"vs_{uuid.uuid4()}",
                status=KycSessionStatus.PENDING,
                attempt_number=1,
            ),
        ]
    )
    db_committing.commit()

    with UnitOfWork(customer_id=customer_a, role=SessionRole.CUSTOMER, db_role=DbRole.APP) as uow:
        visible = {row.customer_id for row in uow.session.execute(select(KycSession)).scalars()}
    assert visible == {customer_a}
