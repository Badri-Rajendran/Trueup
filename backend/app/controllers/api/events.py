"""Customer real-time push (S12 §6, NFR-18): a single self-scoped SSE stream over
`customer:<id>:events`. A dropped/never-open connection is not data loss -- nothing published
over Pub/Sub is ever the sole record of a fact; the next plain `GET` still returns truth.

`_current_customer_id` reads `flask.session["_user_id"]`, not `current_user.id`, to avoid a
`DetachedInstanceError` (`chat.py`/`profile.py`'s precedent).
"""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, stream_with_context
from flask import session as flask_session
from flask_login import current_user

from app.config import get_settings
from app.core.errors import ForbiddenError, UnauthenticatedError
from app.extensions import limiter
from app.integrations.redis.event_bus import RedisEventBus
from app.services.ops.event_publisher import customer_channel
from app.views.events import EventMessage

if TYPE_CHECKING:
    from collections.abc import Iterator

events_bp = Blueprint("events", __name__, url_prefix="/api/v1/events")

_HEARTBEAT_EVENT_TYPE = "heartbeat"
_MAX_STREAM_LIFETIME_SECONDS = 30 * 60
"""Hard cap so a single SSE connection never holds a worker forever -- `EventSource` reconnects."""


def _current_customer_id() -> uuid.UUID:
    if not current_user.is_authenticated:
        raise UnauthenticatedError("Authentication required")
    if current_user.role != "customer":
        raise ForbiddenError("Real-time events are available to customer accounts only")
    raw_user_id = flask_session.get("_user_id")
    if not raw_user_id:
        raise UnauthenticatedError("No authenticated session")
    return uuid.UUID(raw_user_id)


def _generate(channel: str) -> Iterator[str]:
    subscription = RedisEventBus(get_settings().redis_url).subscribe(channel)
    started = time.monotonic()
    try:
        for message in subscription:
            if message.get("event_type") == _HEARTBEAT_EVENT_TYPE:
                yield ": ping\n\n"
            else:
                event = EventMessage.model_validate(dict(message))
                yield f"data: {json.dumps(event.model_dump(mode='json'))}\n\n"
            if time.monotonic() - started >= _MAX_STREAM_LIFETIME_SECONDS:
                return
    finally:
        subscription.close()


@events_bp.route("/stream", methods=["GET"])
@limiter.limit("10 per minute")
def stream_events() -> Any:
    customer_id = _current_customer_id()
    return Response(
        stream_with_context(_generate(customer_channel(str(customer_id)))),
        mimetype="text/event-stream",
    )


__all__ = ["events_bp"]
