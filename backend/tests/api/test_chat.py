"""`POST/GET /api/v1/chat/*` (S11 §6) via the Flask test client: authn/authz, ownership,
throttling, the daily-cap rejection path, and the concurrency-lock rejection path.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import select, text

import app.controllers.api.chat as chat_controller
from app.integrations.openai.fake_agent_adapter import FakeAgentAdapter
from app.models.chat.chat_session import ChatSession, ChatSessionStatus

if TYPE_CHECKING:
    from collections.abc import Iterator

    from flask.testing import FlaskClient
    from sqlalchemy import Engine
    from sqlalchemy.orm import Session

from app.models.chat.chat_message import ChatMessage
from app.models.chat.chat_tool_call import ChatToolCall

CUSTOMER_EMAIL = "chat-customer@trueup.example"
OTHER_EMAIL = "chat-other@trueup.example"
PASSWORD = "correct-horse-battery"

_TABLES = [ChatSession.__table__, ChatMessage.__table__, ChatToolCall.__table__]


@pytest.fixture(autouse=True)
def _chat_tables(owner_engine: Engine) -> Iterator[None]:
    for table in _TABLES:
        table.create(bind=owner_engine, checkfirst=True)
    yield None
    with owner_engine.begin() as connection:
        for table in reversed(_TABLES):
            connection.execute(text(f'DROP TABLE IF EXISTS "{table.name}" CASCADE'))


@pytest.fixture(autouse=True)
def _fake_agent(monkeypatch: pytest.MonkeyPatch) -> FakeAgentAdapter:
    fake = FakeAgentAdapter()
    monkeypatch.setattr(chat_controller, "_agent_port", lambda: fake)
    return fake


def _register_and_login(client: FlaskClient, *, email: str = CUSTOMER_EMAIL) -> tuple[str, str]:
    register_response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": PASSWORD}
    )
    assert register_response.status_code == 201
    customer_id = register_response.get_json()["id"]

    login_response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert login_response.status_code == 200
    csrf_token = login_response.get_json()["csrf_token"]
    return customer_id, csrf_token


def _create_session(client: FlaskClient, csrf_token: str) -> str:
    response = client.post(
        "/api/v1/chat/sessions", headers={"X-CSRFToken": csrf_token}
    )
    assert response.status_code == 201
    return str(response.get_json()["session_id"])


def _read_sse_events(raw_text: str) -> list[dict[str, object]]:
    events = []
    for line in raw_text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line.removeprefix("data: ")))
    return events


# --- POST /sessions ---------------------------------------------------------------------------


def test_list_sessions_requires_authentication(api_client: FlaskClient) -> None:
    """GET is CSRF-exempt, so this isolates the authentication check itself."""
    response = api_client.get("/api/v1/chat/sessions")
    assert response.status_code == 401


def test_create_session_happy_path(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.post("/api/v1/chat/sessions", headers={"X-CSRFToken": csrf_token})

    assert response.status_code == 201
    assert uuid.UUID(response.get_json()["session_id"])


def test_create_session_is_throttled(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    last_response = None
    for _ in range(21):
        last_response = api_client.post(
            "/api/v1/chat/sessions", headers={"X-CSRFToken": csrf_token}
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers


# --- GET /sessions -----------------------------------------------------------------------------


def test_list_sessions_only_returns_the_caller_own_sessions(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    _create_session(api_client, csrf_token)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    _, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    _create_session(api_client, other_csrf)

    response = api_client.get("/api/v1/chat/sessions", headers={"X-CSRFToken": other_csrf})

    assert response.status_code == 200
    assert len(response.get_json()["sessions"]) == 1


# --- GET /sessions/<id>/messages ----------------------------------------------------------------


def test_get_messages_for_another_customers_session_is_not_found(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    _, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    response = api_client.get(
        f"/api/v1/chat/sessions/{session_id}/messages", headers={"X-CSRFToken": other_csrf}
    )

    assert response.status_code == 404


def test_get_messages_for_an_unknown_session_is_not_found(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)

    response = api_client.get(
        f"/api/v1/chat/sessions/{uuid.uuid4()}/messages", headers={"X-CSRFToken": csrf_token}
    )

    assert response.status_code == 404


# --- POST /sessions/<id>/messages (SSE) ---------------------------------------------------------


def test_send_message_happy_path_streams_tokens_then_completes(
    api_client: FlaskClient, _fake_agent: FakeAgentAdapter
) -> None:
    _fake_agent.queue_turn(final_text="you have no holdings yet")
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)

    response = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "what do I hold?"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 200
    events = _read_sse_events(response.get_data(as_text=True))
    assert events[-1]["type"] == "completed"
    assert events[-1]["message_id"]


def test_send_message_requires_ownership(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)
    api_client.post("/api/v1/auth/logout", headers={"X-CSRFToken": csrf_token})

    _, other_csrf = _register_and_login(api_client, email=OTHER_EMAIL)
    response = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "let me see your data"},
        headers={"X-CSRFToken": other_csrf},
    )

    assert response.status_code == 404


def test_send_message_rejects_empty_content(api_client: FlaskClient) -> None:
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)

    response = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": ""},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 422


def test_send_message_rejects_when_daily_cap_reached(
    api_client: FlaskClient, monkeypatch: pytest.MonkeyPatch, _fake_agent: FakeAgentAdapter
) -> None:
    from app.config import get_settings

    capped_settings = get_settings().model_copy(update={"chat_daily_query_cap": 1})
    monkeypatch.setattr(chat_controller, "get_settings", lambda: capped_settings)

    _fake_agent.queue_turn(final_text="first answer")
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)

    first = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "question one"},
        headers={"X-CSRFToken": csrf_token},
    )
    assert first.status_code == 200

    second = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "question two"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert second.status_code == 429
    assert second.get_json()["code"] == "daily_chat_query_cap_exceeded"


def test_send_message_rejects_a_second_concurrent_turn(
    api_client: FlaskClient, owner_engine: Engine
) -> None:
    from sqlalchemy.orm import Session

    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)

    db_session: Session = Session(bind=owner_engine, expire_on_commit=False)
    row = db_session.execute(
        select(ChatSession).where(ChatSession.id == uuid.UUID(session_id))
    ).scalar_one()
    row.status = ChatSessionStatus.STREAMING
    db_session.commit()
    db_session.close()

    response = api_client.post(
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "are you still there?"},
        headers={"X-CSRFToken": csrf_token},
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "chat_turn_in_progress"


def test_send_message_is_throttled(api_client: FlaskClient, _fake_agent: FakeAgentAdapter) -> None:
    _, csrf_token = _register_and_login(api_client)
    session_id = _create_session(api_client, csrf_token)

    last_response = None
    for _ in range(21):
        _fake_agent.queue_turn(final_text="answer")
        last_response = api_client.post(
            f"/api/v1/chat/sessions/{session_id}/messages",
            json={"content": "hi"},
            headers={"X-CSRFToken": csrf_token},
        )

    assert last_response is not None
    assert last_response.status_code == 429
    assert "Retry-After" in last_response.headers
