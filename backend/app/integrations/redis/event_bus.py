"""`RedisEventBus` (S12 §6, NFR-18) -- the only module that talks to Redis Pub/Sub for real-time
push. `app/services/` depends on `EventBusPort`, never this class directly (S0 §3);
`.importlinter`'s `services-use-ports-only` contract forbids `app.services` from importing
`app.integrations.redis`.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping

_HEARTBEAT_MESSAGE: dict[str, str] = {"event_type": "heartbeat"}
_DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 20.0


class RedisEventBus:
    """Implements `EventBusPort` (structural -- no inheritance required)."""

    def __init__(
        self,
        redis_url: str,
        *,
        heartbeat_interval: float = _DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    ) -> None:
        self._client = redis.Redis.from_url(redis_url, decode_responses=True)
        self._heartbeat_interval = heartbeat_interval

    def publish(self, channel: str, message: Mapping[str, str]) -> None:
        self._client.publish(channel, json.dumps(dict(message)))

    def subscribe(self, *channels: str) -> Generator[Mapping[str, str], None, None]:
        """Opens a dedicated `pubsub()` connection, closed in `finally` however the caller stops
        iterating -- via exhaustion, an explicit `.close()`, or garbage collection."""
        pubsub = self._client.pubsub()  # type: ignore[no-untyped-call]  # redis-py ships no stub
        pubsub.subscribe(*channels)
        try:
            while True:
                raw = pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=self._heartbeat_interval
                )
                if raw is None:
                    yield _HEARTBEAT_MESSAGE
                    continue
                decoded: Mapping[str, str] = json.loads(raw["data"])
                yield decoded
        finally:
            pubsub.close()


__all__ = ["RedisEventBus"]
