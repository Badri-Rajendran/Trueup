"""`AgentActionRequestRepository`'s application-layer transition guard (S13 §3.1, ADR 24). Pure:
no database call, no `UnitOfWork` needed."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.models.ops.agent_action_request import (
    AgentActionRequest,
    AgentActionRequestRepository,
    AgentActionStatus,
    AgentActionType,
    InvalidAgentActionTransitionError,
)


def _make_row(status: AgentActionStatus = AgentActionStatus.PENDING) -> AgentActionRequest:
    return AgentActionRequest(
        action=AgentActionType.KYC_OVERRIDE,
        arguments={"customer_id": str(uuid.uuid4()), "reason": "test"},
        requesting_agent="adviser@trueup.test (test token)",
        justification="test",
        status=status,
    )


@pytest.fixture
def repo() -> AgentActionRequestRepository:
    return AgentActionRequestRepository(uow=None)  # type: ignore[arg-type]


def test_approve_from_pending_succeeds(repo: AgentActionRequestRepository) -> None:
    row = _make_row()
    reviewed_by = uuid.uuid4()
    reviewed_at = datetime.now(UTC)

    repo.approve(row, reviewed_by=reviewed_by, reviewed_at=reviewed_at, review_note="looks right")

    assert row.status is AgentActionStatus.APPROVED
    assert row.reviewed_by == reviewed_by
    assert row.reviewed_at == reviewed_at
    assert row.review_note == "looks right"


@pytest.mark.parametrize(
    "status",
    [
        AgentActionStatus.APPROVED,
        AgentActionStatus.REJECTED,
        AgentActionStatus.EXECUTED,
        AgentActionStatus.EXECUTION_FAILED,
    ],
)
def test_approve_from_non_pending_raises(
    repo: AgentActionRequestRepository, status: AgentActionStatus
) -> None:
    row = _make_row(status=status)

    with pytest.raises(InvalidAgentActionTransitionError):
        repo.approve(row, reviewed_by=uuid.uuid4(), reviewed_at=datetime.now(UTC), review_note=None)


def test_reject_from_pending_succeeds(repo: AgentActionRequestRepository) -> None:
    row = _make_row()
    reviewed_by = uuid.uuid4()
    reviewed_at = datetime.now(UTC)

    repo.reject(row, reviewed_by=reviewed_by, reviewed_at=reviewed_at, review_note="not warranted")

    assert row.status is AgentActionStatus.REJECTED
    assert row.reviewed_by == reviewed_by
    assert row.review_note == "not warranted"


def test_reject_from_non_pending_raises(repo: AgentActionRequestRepository) -> None:
    row = _make_row(status=AgentActionStatus.APPROVED)

    with pytest.raises(InvalidAgentActionTransitionError):
        repo.reject(row, reviewed_by=uuid.uuid4(), reviewed_at=datetime.now(UTC), review_note="x")


def test_mark_executed_from_approved_succeeds(repo: AgentActionRequestRepository) -> None:
    row = _make_row(status=AgentActionStatus.APPROVED)
    executed_at = datetime.now(UTC)

    repo.mark_executed(row, executed_at=executed_at)

    assert row.status is AgentActionStatus.EXECUTED
    assert row.executed_at == executed_at


def test_mark_executed_from_pending_raises(repo: AgentActionRequestRepository) -> None:
    row = _make_row(status=AgentActionStatus.PENDING)

    with pytest.raises(InvalidAgentActionTransitionError):
        repo.mark_executed(row, executed_at=datetime.now(UTC))


def test_mark_execution_failed_from_approved_succeeds(repo: AgentActionRequestRepository) -> None:
    row = _make_row(status=AgentActionStatus.APPROVED)

    repo.mark_execution_failed(row, execution_error="reconciliation_break already resolved")

    assert row.status is AgentActionStatus.EXECUTION_FAILED
    assert row.execution_error == "reconciliation_break already resolved"


def test_mark_execution_failed_from_pending_raises(repo: AgentActionRequestRepository) -> None:
    row = _make_row(status=AgentActionStatus.PENDING)

    with pytest.raises(InvalidAgentActionTransitionError):
        repo.mark_execution_failed(row, execution_error="x")
