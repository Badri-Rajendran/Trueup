"""S11 chat security audit (2026-09-07), medium finding -- the daily-cap check-then-insert race.

Before the fix, `ChatUsageLimiter.check()` ran its own `SELECT count(...)` in a transaction that
committed and closed before `ChatOrchestrationService.begin_turn()`'s transaction inserted the new
message row. Under READ COMMITTED (Postgres's default), two concurrent `begin_turn()` calls for
the same customer could each read a count just under the cap and both proceed. The fix acquires a
`pg_advisory_xact_lock` keyed on the customer as the first statement of `begin_turn()`'s
transaction, serializing the cap check against any other in-flight `begin_turn()` for that
customer -- across sessions, not just within one.

This test proves that serialization directly: one thread holds the same lock key while inserting
the message that fills the cap, a second thread's `begin_turn()` call is shown to genuinely block
on that lock (not just get lucky with scheduling) and, once unblocked, correctly sees the
just-committed row and rejects -- the race is closed, not merely less likely.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from app.config import Settings
from app.core.uow import SessionRole
from app.extensions import dispose_engines, init_engines
from app.integrations.openai.fake_agent_adapter import FakeAgentAdapter
from app.models.chat.chat_message import ChatMessage, ChatMessageRole
from app.models.chat.chat_session import ChatSession
from app.models.chat.chat_tool_call import ChatToolCall
from app.models.identity.customer import AccountApprovalStatus, Customer, KycStatus
from app.services.chat.chat_audit_service import ChatAuditService
from app.services.chat.chat_orchestration_service import ChatOrchestrationService
from app.services.chat.chat_usage_limiter import ChatUsageLimiter, DailyQueryCapExceededError
from app.services.chat.read_only_sql_executor import ReadOnlySqlExecutor
from app.services.chat.uow import ChatUnitOfWork

if TYPE_CHECKING:
    from collections.abc import Iterator

    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

_TABLES = [Customer.__table__, ChatSession.__table__, ChatMessage.__table__, ChatToolCall.__table__]

pytestmark = pytest.mark.usefixtures("_tables")


@pytest.fixture(autouse=True)
def _engines(test_settings: Settings) -> Iterator[None]:
    init_engines(test_settings)
    yield None
    dispose_engines()


@pytest.fixture
def _tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


def _customer_with_two_sessions(db_committing: Session) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    customer = Customer(
        email=f"{uuid.uuid4()}@trueup.test",
        password_hash="hash",
        kyc_status=KycStatus.approved,
        account_approval_status=AccountApprovalStatus.approved,
    )
    db_committing.add(customer)
    db_committing.flush()
    session_a = ChatSession(customer_id=customer.id)
    session_b = ChatSession(customer_id=customer.id)
    db_committing.add(session_a)
    db_committing.add(session_b)
    db_committing.commit()
    return customer.id, session_a.id, session_b.id


def _build_orchestration(
    customer_id: uuid.UUID, *, daily_query_cap: int
) -> ChatOrchestrationService:
    def uow_factory() -> ChatUnitOfWork:
        return ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER)

    return ChatOrchestrationService(
        uow_factory=uow_factory,
        usage_limiter=ChatUsageLimiter(daily_query_cap=daily_query_cap),
        audit_service=ChatAuditService(uow_factory),
        agent_port=FakeAgentAdapter(),
        sql_executor=ReadOnlySqlExecutor(),
        max_tool_iterations=6,
    )


def test_concurrent_begin_turn_calls_at_the_cap_boundary_cannot_both_succeed(
    db_committing: Session,
) -> None:
    customer_id, session_a, session_b = _customer_with_two_sessions(db_committing)

    hold_seconds = 0.4
    lock_acquired = threading.Event()
    second_call_blocked_for: list[float] = []
    second_call_outcome: list[str] = []

    def hold_the_customer_lock_and_fill_the_cap() -> None:
        with ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
            # Same lock key `ChatOrchestrationService.begin_turn()` acquires.
            uow.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:customer_id)::bigint)"),
                {"customer_id": str(customer_id)},
            )
            lock_acquired.set()
            time.sleep(hold_seconds)
            uow.chat_messages.add(
                ChatMessage(
                    session_id=session_a, role=ChatMessageRole.USER, content="first question"
                )
            )
            uow.commit()

    def attempt_begin_turn_at_the_cap() -> None:
        orchestration = _build_orchestration(customer_id, daily_query_cap=1)
        started_at = time.monotonic()
        try:
            orchestration.begin_turn(
                session_id=session_b, customer_id=customer_id, message_text="second question"
            )
            second_call_outcome.append("began")
        except DailyQueryCapExceededError:
            second_call_outcome.append("rejected")
        second_call_blocked_for.append(time.monotonic() - started_at)

    holder_thread = threading.Thread(target=hold_the_customer_lock_and_fill_the_cap)
    holder_thread.start()
    assert lock_acquired.wait(timeout=5), "holder thread never acquired the advisory lock"

    challenger_thread = threading.Thread(target=attempt_begin_turn_at_the_cap)
    challenger_thread.start()
    holder_thread.join(timeout=5)
    challenger_thread.join(timeout=5)

    assert len(second_call_outcome) == 1, "challenger thread never completed"
    # Assert on the challenger's own block duration -- a genuine cross-connection lock wait, not a
    # Python thread-scheduling coincidence. Tolerance below the full hold; near-instant would mean
    # the two transactions interleaved instead of serializing.
    assert second_call_blocked_for[0] >= hold_seconds * 0.75
    # Unblocked only after the holder committed the capping row -- so the challenger's own count
    # check sees it and correctly rejects, closing the race rather than narrowing its window.
    assert second_call_outcome == ["rejected"]


def test_second_session_can_begin_a_turn_once_the_first_is_under_the_cap(
    db_committing: Session,
) -> None:
    """Sanity check alongside the race test: the lock serializes, it does not wrongly block a
    second session's turn when the customer is still under the cap."""
    customer_id, _session_a, session_b = _customer_with_two_sessions(db_committing)

    orchestration = _build_orchestration(customer_id, daily_query_cap=5)
    begun = orchestration.begin_turn(
        session_id=session_b, customer_id=customer_id, message_text="only question"
    )

    assert begun.session_id == session_b
