"""`@requires_role`, `@requires_ownership`, `@audited` (S0 §7.2).

Pure unit tests — a bare `Flask()` app supplies request/app context (`requires_ownership`/
`audited` read `flask.request`), and `@audited`'s "same transaction" guarantee is exercised
against the real `UnitOfWork` with a fake `Session` substituted via `session_factory` (S0 §5's own
documented extension point), never a real database. Faking the `Session` — rather than the whole
`UnitOfWork` — is what lets the rollback assertion below use `UnitOfWork`'s real `__exit__`, not a
hand-rolled stand-in for it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from flask import Flask

from app.core import security
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.core.security import AuditSink, audited, requires_ownership, requires_role
from app.core.uow import SessionRole, UnitOfWork


@dataclass
class _FakeUser:
    id: uuid.UUID
    role: str
    is_authenticated: bool = True


_ANONYMOUS = _FakeUser(id=uuid.uuid4(), role="customer", is_authenticated=False)


@pytest.fixture
def flask_app() -> Flask:
    """A bare app, not `create_app()` — this suite never touches a database or Redis."""
    return Flask(__name__)


@pytest.fixture(autouse=True)
def _clean_audit_sink() -> Any:
    yield None
    security.reset_audit_sink()


# --- requires_role -------------------------------------------------------------------------


def test_requires_role_rejects_unauthenticated(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _ANONYMOUS)

    @requires_role("adviser")
    def view() -> str:
        return "secret"

    with flask_app.test_request_context(), pytest.raises(UnauthenticatedError):
        view()


def test_requires_role_rejects_wrong_role(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="customer"))

    @requires_role("adviser", "admin")
    def view() -> str:
        return "secret"

    with flask_app.test_request_context(), pytest.raises(ForbiddenError):
        view()


def test_requires_role_admits_a_matching_role(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="adviser"))

    @requires_role("adviser", "admin")
    def view() -> str:
        return "secret"

    with flask_app.test_request_context():
        assert view() == "secret"


def test_requires_role_admits_a_staff_role_value_not_just_str_literals(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    """Regression guard for the `StaffRole(enum.Enum)` bug (`tests/unit/test_staff.py`): a real
    `Staff.role` value must satisfy `in ("adviser", "admin")` the same way a plain string does."""
    from app.models.identity.staff import StaffRole

    monkeypatch.setattr(
        security, "current_user", _FakeUser(id=uuid.uuid4(), role=StaffRole.adviser)
    )

    @requires_role("adviser", "admin")
    def view() -> str:
        return "secret"

    with flask_app.test_request_context():
        assert view() == "secret"


# --- requires_ownership ---------------------------------------------------------------------


def test_requires_ownership_rejects_unauthenticated(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _ANONYMOUS)

    @requires_ownership()
    def view(customer_id: uuid.UUID) -> str:
        return "ok"

    with flask_app.test_request_context(), pytest.raises(UnauthenticatedError):
        view(customer_id=uuid.uuid4())


def test_requires_ownership_rejects_a_missing_customer_id(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="customer"))

    @requires_ownership()
    def view(**kwargs: Any) -> str:
        return "ok"

    with (
        flask_app.test_request_context(),
        pytest.raises(ForbiddenError, match="Customer ID required"),
    ):
        view()


def test_requires_ownership_rejects_a_customer_reading_someone_elses_resource(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    own_id = uuid.uuid4()
    monkeypatch.setattr(security, "current_user", _FakeUser(id=own_id, role="customer"))

    @requires_ownership()
    def view(customer_id: uuid.UUID) -> str:
        return "ok"

    with flask_app.test_request_context(), pytest.raises(ForbiddenError):
        view(customer_id=uuid.uuid4())


def test_requires_ownership_admits_a_customer_reading_their_own_resource(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    own_id = uuid.uuid4()
    monkeypatch.setattr(security, "current_user", _FakeUser(id=own_id, role="customer"))

    @requires_ownership()
    def view(customer_id: uuid.UUID) -> str:
        return "ok"

    with flask_app.test_request_context():
        assert view(customer_id=own_id) == "ok"


def test_requires_ownership_admits_adviser_regardless_of_target(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="adviser"))

    @requires_ownership()
    def view(customer_id: uuid.UUID) -> str:
        return "ok"

    with flask_app.test_request_context():
        assert view(customer_id=uuid.uuid4()) == "ok"


def test_requires_ownership_reads_customer_id_from_json_body(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    own_id = uuid.uuid4()
    monkeypatch.setattr(security, "current_user", _FakeUser(id=own_id, role="customer"))

    @requires_ownership()
    def view() -> str:
        return "ok"

    with flask_app.test_request_context(json={"customer_id": str(own_id)}):
        assert view() == "ok"


def test_requires_ownership_rejects_an_unknown_role(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="superuser"))

    @requires_ownership()
    def view(customer_id: uuid.UUID) -> str:
        return "ok"

    with flask_app.test_request_context(), pytest.raises(ForbiddenError, match="Unknown role"):
        view(customer_id=uuid.uuid4())


# --- audited ---------------------------------------------------------------------------------


class _FakeSession:
    """Just enough of `sqlalchemy.orm.Session` for `UnitOfWork` to drive, with `rollback()`
    discarding staged-but-uncommitted `add()`s the way a real ROLLBACK would."""

    def __init__(self) -> None:
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, *args: Any, **kwargs: Any) -> None:
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1
        self.added.clear()

    def close(self) -> None:
        self.closed = True


class _FakeAuditSink(AuditSink):
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    def record(
        self,
        uow: UnitOfWork,
        *,
        actor_id: uuid.UUID,
        action: str,
        target_customer_id: uuid.UUID | None,
        payload_hash: str,
    ) -> None:
        assert uow.session is self._session  # same transaction as the caller's uow
        uow.session.add(
            {
                "actor_id": actor_id,
                "action": action,
                "target_customer_id": target_customer_id,
                "payload_hash": payload_hash,
            }
        )


def _uow() -> tuple[UnitOfWork, _FakeSession]:
    fake_session = _FakeSession()
    uow = UnitOfWork(
        customer_id=None,
        role=SessionRole.ADMIN,
        session_factory=lambda: fake_session,
    )
    return uow, fake_session


def test_audited_requires_authentication(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _ANONYMOUS)
    uow, _ = _uow()

    @audited("view_customer")
    def action(uow: UnitOfWork, customer_id: uuid.UUID) -> str:
        return "ok"

    target = uuid.uuid4()
    with (
        flask_app.test_request_context(json={"customer_id": str(target)}),
        pytest.raises(UnauthenticatedError),
    ):
        action(uow, customer_id=target)


def test_audited_requires_an_installed_sink(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="adviser"))
    uow, _fake_session = _uow()

    @audited("view_customer")
    def action(uow: UnitOfWork, customer_id: uuid.UUID) -> str:
        return "ok"

    target = uuid.uuid4()
    with (
        flask_app.test_request_context(json={"customer_id": str(target)}),
        uow,
        pytest.raises(RuntimeError, match="No AuditSink installed"),
    ):
        action(uow, customer_id=target)


def test_audited_writes_the_row_in_the_same_uow_and_commits_together(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    actor_id = uuid.uuid4()
    monkeypatch.setattr(security, "current_user", _FakeUser(id=actor_id, role="adviser"))
    uow, fake_session = _uow()
    security.set_audit_sink(_FakeAuditSink(fake_session))

    calls: list[str] = []

    @audited("view_customer_ledger")
    def action(uow: UnitOfWork, customer_id: uuid.UUID) -> str:
        calls.append("action-ran")
        return "ok"

    target = uuid.uuid4()
    with flask_app.test_request_context(json={"customer_id": str(target)}), uow:
        result = action(uow, customer_id=target)
        uow.commit()

    assert result == "ok"
    assert calls == ["action-ran"]
    assert len(fake_session.added) == 1
    assert fake_session.added[0]["actor_id"] == actor_id
    assert fake_session.added[0]["action"] == "view_customer_ledger"
    assert fake_session.added[0]["target_customer_id"] == target
    assert fake_session.commits == 1
    assert fake_session.rollbacks == 0


def test_audited_rolls_back_the_audit_row_when_the_action_raises(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    """The required explicit case: an audited action can never succeed with no audit trail, and
    symmetrically, an audit row can never survive an action that failed — the decorator writes to
    `uow.session`, not to its own transaction, so `UnitOfWork.__exit__`'s rollback-on-exception
    (S0 §5) discards both together."""
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="admin"))
    uow, fake_session = _uow()
    security.set_audit_sink(_FakeAuditSink(fake_session))

    @audited("resolve_reconciliation_break")
    def action(uow: UnitOfWork, customer_id: uuid.UUID) -> str:
        raise ValueError("boom — the action failed after the audit row was staged")

    target = uuid.uuid4()
    with (
        flask_app.test_request_context(json={"customer_id": str(target)}),
        pytest.raises(ValueError, match="boom"),
        uow,
    ):
        action(uow, customer_id=target)
        uow.commit()  # never reached

    assert fake_session.commits == 0
    assert fake_session.rollbacks == 1
    assert fake_session.added == []  # the staged audit row did not survive the rollback


def test_audited_allows_a_missing_target_customer_id(
    monkeypatch: pytest.MonkeyPatch, flask_app: Flask
) -> None:
    """`admin_audit_log.target_customer_id` is nullable (S7 §5.2: resolving a
    `reconciliation_break` with no single-customer attribution) -- an audited action with no
    target customer still records, with `target_customer_id=None`, rather than raising."""
    monkeypatch.setattr(security, "current_user", _FakeUser(id=uuid.uuid4(), role="admin"))
    uow, fake_session = _uow()
    security.set_audit_sink(_FakeAuditSink(fake_session))

    @audited("view_customer")
    def action(uow: UnitOfWork) -> str:
        return "ok"

    with flask_app.test_request_context(json={}), uow:
        result = action(uow)
        uow.commit()

    assert result == "ok"
    assert len(fake_session.added) == 1
    assert fake_session.added[0]["target_customer_id"] is None
