"""`FakeEventBus` -- an in-memory `EventBusPort` for tests, mirroring `fake_broker.py`'s style: it
records every published message and lets a test push one and assert `subscribe` yields it.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator, Mapping


class FakeEventBus:
    """Implements `EventBusPort` (structural -- no inheritance required)."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, str]]] = []
        """Every `(channel, message)` pair passed to `publish`, in call order."""
        self._pending: dict[str, list[dict[str, str]]] = defaultdict(list)

    def publish(self, channel: str, message: Mapping[str, str]) -> None:
        payload = dict(message)
        self.published.append((channel, payload))
        self._pending[channel].append(payload)

    def subscribe(self, *channels: str) -> Generator[Mapping[str, str], None, None]:
        """Pull-based: yields a queued message for one of `channels` as soon as `publish` has put
        one there, else a heartbeat sentinel -- never sleeps, so a test drives it with `next()`."""
        while True:
            for channel in channels:
                queue = self._pending[channel]
                if queue:
                    yield queue.pop(0)
                    break
            else:
                yield {"event_type": "heartbeat"}


__all__ = ["FakeEventBus"]
