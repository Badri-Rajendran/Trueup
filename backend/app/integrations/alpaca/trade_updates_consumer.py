"""`TradeUpdatesConsumer` (S3 §6, ADR 22) — the always-on `trade_updates` websocket consumer.

No precedent elsewhere in this codebase (ADR 22's own text), so the design choices here are
S3's own, laid out explicitly rather than left implicit:

- **Split pure logic from the network transport.** `handle_message` — validate, compute the
  dedupe key, hand off to `EventIntakeService` — takes a plain `dict` and has no socket, no
  `asyncio`, and no Alpaca SDK object in its signature. It is exactly what the S3 contract suite
  exercises (ADR 22's consequence: "a test never opens a websocket") and exactly what
  `FakeBrokerAdapter`-driven tests feed synthetic fill/reject/cancel/expired payloads into.
  `run_forever` is the thin, untested-by-unit-tests wiring onto
  `alpaca.trading.stream.TradingStream` — the same "adapter is thin, logic is tested separately"
  split `AlpacaCalendarAdapter`/`AlpacaBrokerAdapter` already follow, just with a persistent
  connection instead of a request.
- **`source_event_id`.** ADR 22 states it for fills (`execution_id`) but the `inbound_event`
  table's dedupe key is `NOT NULL`, and Alpaca's `new`/`canceled`/`expired`/`rejected` events carry
  no `execution_id` at all. This module derives one for those:
  `f"{alpaca_order_id}:{event}:{timestamp epoch}"` — deterministic given the identical message, so
  a redelivered non-fill event dedupes exactly like a redelivered fill does (generalizing FR-9's
  intent beyond the fills the requirement names explicitly), without inventing a new mechanism —
  it reuses `inbound_event`'s existing `UNIQUE (source, source_event_id)` constraint.
- **Which Alpaca events are tracked.** ADR 22 names `new`, `fill`, `partial_fill`, `canceled`,
  `expired`, `rejected`. `new` maps to this system's own `OrderEventType.ACCEPTED` — Alpaca's own
  vocabulary differs from S3 §3.2's chosen enum naming, not a different concept. `fill` and
  `partial_fill` both map to `OrderEventType.FILL`: `OrderProjectionService.fold` already derives
  `filled`-vs-`partially_filled` from cumulative `filled_quantity` against `quantity_requested`, so
  Alpaca's own full/partial distinction would be redundant to also carry through here. Any other
  Alpaca event (`pending_new`, `replaced`, ...) is intentionally ignored — logged, not inserted —
  since S3's state machine has no corresponding transition for it; a garbage or malformed payload
  is instead rejected by Pydantic validation before that filter is even reached, per foundation
  spec §6.
- **`signature_verified = true` unconditionally** (`TrustedTransportVerifier`), per ADR 22: the
  authenticated outbound TLS session Trueup itself opened to Alpaca is the trust anchor here, not a
  per-message signature — stated explicitly so this source's `signature_verified` column does not
  read as silently different from Stripe/Plaid's for the wrong reason.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict

from app.core.logging import get_logger
from app.models.ops.inbound_event import InboundEventSource
from app.services.intake.event_intake import IncomingEvent, IntakeResult

if TYPE_CHECKING:
    from datetime import timedelta

    from app.services.intake.event_intake import EventIntakeService

log = get_logger(__name__)

_HANDLED_EVENTS = frozenset({"new", "fill", "partial_fill", "canceled", "expired", "rejected"})


class _AlpacaTradeUpdateOrder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    client_order_id: str
    symbol: str


class AlpacaTradeUpdateMessage(BaseModel):
    """The validated envelope (foundation spec §6: every payload is parsed through a Pydantic
    model before any service sees it) — a deliberately narrow subset of Alpaca's real
    `TradeUpdate` shape, only the fields this system's own event folding needs."""

    model_config = ConfigDict(extra="ignore")

    event: str
    execution_id: str | None = None
    order: _AlpacaTradeUpdateOrder
    timestamp: datetime
    price: str | None = None
    qty: str | None = None


class TrustedTransportVerifier:
    """ADR 22: the authenticated outbound TLS session to Alpaca is the trust anchor; there is no
    per-message signature to check for this source."""

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        return True


def source_event_id_for(message: AlpacaTradeUpdateMessage) -> str:
    """ADR 7's dedupe key for a fill (`execution_id`), generalized to every event type this
    module tracks (module docstring)."""
    if message.execution_id is not None:
        return message.execution_id
    return f"{message.order.id}:{message.event}:{message.timestamp.timestamp()}"


class TradeUpdatesConsumer:
    def __init__(self, *, intake: EventIntakeService) -> None:
        self._intake = intake

    def handle_message(self, raw: dict[str, Any]) -> IntakeResult | None:
        """Validate, dedupe-key, and hand `raw` to the shared intake path. Returns `None` for an
        Alpaca event this system's state machine has no transition for (module docstring) —
        distinct from `IntakeResult`, which only describes outcomes for events actually intaken.
        """
        message = AlpacaTradeUpdateMessage.model_validate(raw)
        if message.event not in _HANDLED_EVENTS:
            log.info("alpaca_trade_update_ignored", alpaca_event=message.event)
            return None

        event = IncomingEvent(
            source=InboundEventSource.ALPACA,
            source_event_id=source_event_id_for(message),
            payload=raw,
        )
        return self._intake.intake(
            event,
            raw_payload=json.dumps(raw, sort_keys=True).encode("utf-8"),
            signature=None,
        )

    def run_forever(
        self,
        *,
        api_key_id: str,
        api_secret_key: str,
        paper: bool = True,
        stale_after: timedelta,
    ) -> None:
        """The real, network-touching wiring onto `alpaca.trading.stream.TradingStream` — not
        exercised by unit tests (module docstring); `handle_message` above is. Blocking: `.run()`
        drives its own internal event loop. `tenacity` retries the connection with exponential
        backoff; a gap since the last received message longer than `stale_after` is logged as an
        operational alert rather than silently retried forever (ADR 22 — NFR-6's honest-
        degradation stance)."""
        import tenacity
        from alpaca.trading.stream import TradingStream

        last_message_at = datetime.now(UTC)

        async def _on_message(raw_message: object) -> None:
            nonlocal last_message_at
            last_message_at = datetime.now(UTC)
            payload = (
                raw_message.model_dump(mode="json")
                if hasattr(raw_message, "model_dump")
                else dict(raw_message)  # type: ignore[call-overload]
            )
            self.handle_message(payload)

        @tenacity.retry(
            wait=tenacity.wait_exponential(multiplier=1, max=60),
            reraise=True,
        )
        def _connect_and_run() -> None:
            gap = datetime.now(UTC) - last_message_at
            if gap > stale_after:
                log.error(
                    "alpaca_trade_updates_stream_stale",
                    seconds_since_last_message=gap.total_seconds(),
                )
            stream = TradingStream(api_key=api_key_id, secret_key=api_secret_key, paper=paper)
            stream.subscribe_trade_updates(_on_message)
            stream.run()

        _connect_and_run()


__all__ = [
    "AlpacaTradeUpdateMessage",
    "TradeUpdatesConsumer",
    "TrustedTransportVerifier",
    "source_event_id_for",
]
