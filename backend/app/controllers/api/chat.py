"""Chat routes (S11 §6) — session create/list, SSE message stream, message history. Customer-only
(S11 §2), so every route rejects a staff session with 403.

`_current_customer_id` reads `flask.session["_user_id"]`, not `current_user.id`, to avoid a
`DetachedInstanceError` (see `funding.py`).
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, jsonify, request, stream_with_context
from flask import session as flask_session
from flask_login import current_user
from pydantic import BaseModel, Field
from pydantic import ValidationError as PydanticValidationError

from app.config import get_settings
from app.core.errors import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    UnauthenticatedError,
    ValidationError,
)
from app.core.uow import SessionRole
from app.extensions import limiter
from app.integrations.openai.fake_agent_adapter import FakeAgentAdapter
from app.integrations.openai.llm_agent_port import (
    ChatCompletedEvent,
    ChatTokenEvent,
)
from app.models.chat.chat_session import ChatSession
from app.services.chat.chat_audit_service import ChatAuditService
from app.services.chat.chat_orchestration_service import (
    ChatOrchestrationService,
    TurnAlreadyInProgressError,
)
from app.services.chat.chat_usage_limiter import ChatUsageLimiter, DailyQueryCapExceededError
from app.services.chat.read_only_sql_executor import ReadOnlySqlExecutor
from app.services.chat.uow import ChatUnitOfWork
from app.views.chat import (
    ChatMessageResponse,
    ChatMessagesListResponse,
    ChatSessionCreatedResponse,
    ChatSessionsListResponse,
    ChatSessionSummaryResponse,
    ChatStreamCompletedEvent,
    ChatStreamErrorEvent,
    ChatStreamTokenEvent,
    ChatToolCallSummaryView,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from app.integrations.openai.llm_agent_port import LlmAgentPort

chat_bp = Blueprint("chat", __name__, url_prefix="/api/v1/chat")


class _SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


def _current_customer_id() -> uuid.UUID:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Chat is available to customer accounts only")
    raw_user_id = flask_session.get("_user_id")
    if not raw_user_id:
        raise UnauthenticatedError("No authenticated session")
    return uuid.UUID(raw_user_id)


def _agent_port() -> LlmAgentPort:
    settings = get_settings()
    if not settings.has_openai_credentials:
        if settings.is_production:
            raise RuntimeError("OPENAI_API_KEY is required in production")
        return FakeAgentAdapter()

    from app.integrations.openai.openai_agent_adapter import OpenAIAgentAdapter

    assert settings.openai_api_key is not None  # narrowed by has_openai_credentials above
    return OpenAIAgentAdapter(
        api_key=settings.openai_api_key.get_secret_value(),
        org_id=settings.openai_org_id,
        model=settings.openai_chat_model,
    )


def _build_orchestration_service(customer_id: uuid.UUID) -> ChatOrchestrationService:
    settings = get_settings()

    def uow_factory() -> ChatUnitOfWork:
        return ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER)

    return ChatOrchestrationService(
        uow_factory=uow_factory,
        usage_limiter=ChatUsageLimiter(uow_factory, daily_query_cap=settings.chat_daily_query_cap),
        audit_service=ChatAuditService(uow_factory),
        agent_port=_agent_port(),
        sql_executor=ReadOnlySqlExecutor(),
        max_tool_iterations=settings.chat_max_tool_iterations,
    )


def _get_owned_session(customer_id: uuid.UUID, session_id: uuid.UUID) -> ChatSession:
    with ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        session = uow.chat_sessions.get_by_id(session_id)
    # RLS already makes another customer's session invisible (S0 §7.3).
    if session is None:
        raise NotFoundError("chat session not found")
    return session


@chat_bp.route("/sessions", methods=["POST"])
@limiter.limit("20 per minute")
def create_session() -> Any:
    customer_id = _current_customer_id()
    with ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        session = ChatSession(customer_id=customer_id)
        uow.chat_sessions.add(session)
        uow.commit()
        view = ChatSessionCreatedResponse(session_id=session.id)
    return jsonify(view.model_dump(mode="json")), 201


@chat_bp.route("/sessions", methods=["GET"])
@limiter.limit("60 per minute")
def list_sessions() -> Any:
    customer_id = _current_customer_id()
    with ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        rows = uow.chat_sessions.list_for_customer(customer_id)
        view = ChatSessionsListResponse(
            sessions=[
                ChatSessionSummaryResponse(
                    id=row.id, status=row.status.value, created_at=row.created_at
                )
                for row in rows
            ]
        )
    return jsonify(view.model_dump(mode="json")), 200


@chat_bp.route("/sessions/<uuid:session_id>/messages", methods=["GET"])
@limiter.limit("60 per minute")
def list_messages(session_id: uuid.UUID) -> Any:
    customer_id = _current_customer_id()
    _get_owned_session(customer_id, session_id)
    with ChatUnitOfWork(customer_id=customer_id, role=SessionRole.CUSTOMER) as uow:
        rows = uow.chat_messages.list_for_session(session_id)
        view = ChatMessagesListResponse(
            messages=[
                ChatMessageResponse(
                    id=row.id, role=row.role.value, content=row.content, created_at=row.created_at
                )
                for row in rows
                if row.content or row.role.value == "user"
            ]
        )
    return jsonify(view.model_dump(mode="json")), 200


@chat_bp.route("/sessions/<uuid:session_id>/messages", methods=["POST"])
@limiter.limit("20 per minute")
def send_message(session_id: uuid.UUID) -> Any:
    customer_id = _current_customer_id()
    _get_owned_session(customer_id, session_id)

    try:
        body = _SendMessageRequest.model_validate(request.get_json(silent=True) or {})
    except PydanticValidationError as exc:
        raise ValidationError(str(exc)) from exc

    orchestration = _build_orchestration_service(customer_id)

    try:
        begun = orchestration.begin_turn(
            session_id=session_id, customer_id=customer_id, message_text=body.content
        )
    except DailyQueryCapExceededError as exc:
        raise RateLimitedError(str(exc), code="daily_chat_query_cap_exceeded") from exc
    except TurnAlreadyInProgressError as exc:
        raise ConflictError(str(exc), code="chat_turn_in_progress") from exc

    def _generate() -> Iterator[str]:
        payload: ChatStreamTokenEvent | ChatStreamCompletedEvent | ChatStreamErrorEvent
        for event in orchestration.stream_turn(begun, body.content):
            if isinstance(event, ChatTokenEvent):
                payload = ChatStreamTokenEvent(text=event.text)
            elif isinstance(event, ChatCompletedEvent):
                payload = ChatStreamCompletedEvent(
                    message_id=begun.assistant_message_id,
                    tool_calls=[
                        ChatToolCallSummaryView(tool_name=call.tool_name, summary=call.summary)
                        for call in event.tool_calls
                    ],
                )
            else:
                payload = ChatStreamErrorEvent(message=event.message)
            yield f"data: {json.dumps(payload.model_dump(mode='json'))}\n\n"

    return Response(stream_with_context(_generate()), mimetype="text/event-stream")


__all__ = ["chat_bp"]
