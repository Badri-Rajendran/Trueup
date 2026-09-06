"""`agent_action_request`'s DB-level single-transition guard (S13 §3.1, ADR 24) and concurrent
approve/reject serialization on `get_for_update` (S13 §6 edge case 2)."""

from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import DbRole
from app.core.uow import SessionRole
from app.models.ops.agent_action_request import (
    AgentActionRequest,
    AgentActionStatus,
    AgentActionType,
    InvalidAgentActionTransitionError,
)
from app.services.agent_surface.uow import AgentSurfaceUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine

pytestmark = pytest.mark.usefixtures("_agent_action_request_table")


@pytest.fixture
def _agent_action_request_table(owner_engine: Engine) -> Iterator[None]:
    AgentActionRequest.__table__.create(bind=owner_engine, checkfirst=True)
    yield None
    AgentActionRequest.__table__.drop(bind=owner_engine, checkfirst=True)


def _insert_pending(db_committing) -> AgentActionRequest:
    row = AgentActionRequest(
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(uuid.uuid4()), "reason": "test"},
        requesting_agent="adviser@trueup.test (test token)",
        justification="test justification",
        status=AgentActionStatus.PENDING,
    )
    db_committing.add(row)
    db_committing.commit()
    return row


# --- CHECK constraints (S13 §3.1) --------------------------------------------------------------


def test_justification_must_be_non_empty_at_the_db_level(db_committing) -> None:
    row = AgentActionRequest(
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(uuid.uuid4())},
        requesting_agent="adviser@trueup.test",
        justification="",
    )
    db_committing.add(row)
    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


def test_approved_status_requires_a_reviewer_at_the_db_level(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.APPROVED  # reviewed_by/reviewed_at left null -- must fail
    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


def test_executed_status_requires_executed_at_at_the_db_level(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.APPROVED
    row.reviewed_by = uuid.uuid4()
    row.reviewed_at = datetime.now(UTC)
    db_committing.commit()

    row.status = AgentActionStatus.EXECUTED  # executed_at left null -- must fail
    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


def test_execution_failed_status_requires_an_error_at_the_db_level(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.APPROVED
    row.reviewed_by = uuid.uuid4()
    row.reviewed_at = datetime.now(UTC)
    db_committing.commit()

    row.status = AgentActionStatus.EXECUTION_FAILED  # execution_error left null -- must fail
    with pytest.raises((IntegrityError, DBAPIError)):
        db_committing.commit()


# --- the trigger itself (OLD.status -> NEW.status) ---------------------------------------------


def test_pending_may_not_jump_straight_to_executed(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.EXECUTED
    row.executed_at = datetime.now(UTC)
    with pytest.raises(DBAPIError, match="may only move from pending"):
        db_committing.commit()


def test_approved_may_not_revert_to_pending(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.APPROVED
    row.reviewed_by = uuid.uuid4()
    row.reviewed_at = datetime.now(UTC)
    db_committing.commit()

    row.status = AgentActionStatus.PENDING
    with pytest.raises(DBAPIError, match="may only move approved"):
        db_committing.commit()


def test_a_terminal_row_cannot_be_updated_again(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.REJECTED
    row.reviewed_by = uuid.uuid4()
    row.reviewed_at = datetime.now(UTC)
    db_committing.commit()

    row.review_note = "trying to change it after the fact"
    with pytest.raises(DBAPIError, match="already terminal"):
        db_committing.commit()


def test_identifying_fields_are_immutable_across_a_legal_transition(db_committing) -> None:
    row = _insert_pending(db_committing)
    row.status = AgentActionStatus.REJECTED
    row.reviewed_by = uuid.uuid4()
    row.reviewed_at = datetime.now(UTC)
    row.justification = "rewritten after the fact"
    with pytest.raises(DBAPIError, match="identifying fields are immutable"):
        db_committing.commit()


def test_delete_is_revoked_for_trueup_app(app_engine: Engine, db_committing) -> None:
    row = _insert_pending(db_committing)

    with app_engine.begin() as connection, pytest.raises(DBAPIError, match="permission denied"):
        connection.execute(
            AgentActionRequest.__table__.delete().where(AgentActionRequest.id == row.id)
        )


# --- S13 §6 edge case 2: concurrent approve/reject -----------------------------------------------


def test_concurrent_approval_attempts_serialize_on_the_row_lock(db_committing) -> None:
    row = _insert_pending(db_committing)
    request_id = row.id

    hold_seconds = 0.4
    first_locked = threading.Event()
    second_blocked_for: list[float] = []
    second_outcome: list[str] = []

    def hold_the_lock_then_approve() -> None:
        with AgentSurfaceUnitOfWork(
            customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP
        ) as uow:
            locked = uow.agent_action_requests.get_for_update(request_id)
            assert locked is not None
            first_locked.set()
            time.sleep(hold_seconds)
            uow.agent_action_requests.approve(
                locked, reviewed_by=uuid.uuid4(), reviewed_at=datetime.now(UTC), review_note="a"
            )
            uow.commit()

    def attempt_a_second_approval() -> None:
        with AgentSurfaceUnitOfWork(
            customer_id=None, role=SessionRole.ADVISER, db_role=DbRole.APP
        ) as uow:
            started_at = time.monotonic()
            locked = uow.agent_action_requests.get_for_update(request_id)
            second_blocked_for.append(time.monotonic() - started_at)
            assert locked is not None
            try:
                uow.agent_action_requests.approve(
                    locked,
                    reviewed_by=uuid.uuid4(),
                    reviewed_at=datetime.now(UTC),
                    review_note="b",
                )
                uow.commit()
                second_outcome.append("approved")
            except InvalidAgentActionTransitionError:
                uow.rollback()
                second_outcome.append("rejected_as_already_approved")

    first_thread = threading.Thread(target=hold_the_lock_then_approve)
    first_thread.start()
    assert first_locked.wait(timeout=5), "first thread never acquired the row lock"

    second_thread = threading.Thread(target=attempt_a_second_approval)
    second_thread.start()
    first_thread.join(timeout=5)
    second_thread.join(timeout=5)

    assert len(second_blocked_for) == 1, "second thread never completed"
    assert second_blocked_for[0] >= hold_seconds * 0.75
    assert second_outcome == ["rejected_as_already_approved"]
