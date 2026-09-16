"""SSE payload schema for `app/controllers/api/events.py` and `app/controllers/admin/events.py`
(S12 §6). Explicit allow-list only, mirroring `app/views/chat.py`'s precedent -- the pushed event
is a contract too, not just an internal detail, and it must never carry more than a pointer for
the client to re-fetch by (S12 §6: never trust this payload as authoritative data).
"""

from __future__ import annotations

from pydantic import BaseModel


class EventMessage(BaseModel):
    event_type: str
    entity_id: str
    summary: str


__all__ = ["EventMessage"]
