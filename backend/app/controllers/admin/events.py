"""Adviser/admin real-time push (S12 §6, NFR-18): a single SSE stream over `adviser:events`,
carrying newly-opened reconciliation breaks. Staff-only (`@requires_role`); a dropped/never-open
connection is not data loss -- see `app/controllers/api/events.py`'s module docstring.
"""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

from flask import Blueprint, Response, stream_with_context

from app.config import get_settings
from app.core.security import requires_role
from app.extensions import limiter
from app.integrations.redis.event_bus import RedisEventBus
from app.services.ops.event_publisher import ADVISER_CHANNEL
from app.views.events import EventMessage

if TYPE_CHECKING:
    from collections.abc import Iterator

admin_events_bp = Blueprint("admin_events", __name__, url_prefix="/api/v1/admin/events")

_HEARTBEAT_EVENT_TYPE = "heartbeat"
_MAX_STREAM_LIFETIME_SECONDS = 30 * 60
"""Hard cap so a single SSE connection never holds a worker forever -- `EventSource` reconnects."""

_STAFF_ROLES = ("adviser", "admin")


def _generate() -> Iterator[str]:
    subscription = RedisEventBus(get_settings().redis_url).subscribe(ADVISER_CHANNEL)
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


@admin_events_bp.route("/stream", methods=["GET"])
@limiter.limit("10 per minute")
@requires_role(*_STAFF_ROLES)
def stream_admin_events() -> Any:
    return Response(stream_with_context(_generate()), mimetype="text/event-stream")


__all__ = ["admin_events_bp"]
