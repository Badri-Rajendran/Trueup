"""`TradeUpdatesConsumer` (S3 §6, ADR 22) — the always-on `trade_updates` websocket consumer.

`handle_message` is pure (no socket/asyncio) and is what the S3 contract suite exercises;
`run_forever` is the thin, untested wiring onto `alpaca.trading.stream.TradingStream`.
`source_event_id_for` derives a dedupe key for non-fill events, which carry no `execution_id`.
Only `new`/`fill`/`partial_fill`/`canceled`/`expired`/`rejected` are tracked (ADR 22); any other
event is logged and ignored. `signature_verified = true` unconditionally — the outbound TLS
session is the trust anchor, not a per-message signature (ADR 22).
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
    """The validated envelope (foundation spec §6) — a narrow subset of Alpaca's `TradeUpdate` shape."""

    model_config = ConfigDict(extra="ignore")

    event: str
    execution_id: str | None = None
    order: _AlpacaTradeUpdateOrder
    timestamp: datetime
    price: str | None = None
    qty: str | None = None


class TrustedTransportVerifier:
    """ADR 22: the outbound TLS session to Alpaca is the trust anchor; no per-message signature."""

    def verify(self, *, payload: bytes, signature: str | None) -> bool:
        return True


def source_event_id_for(message: AlpacaTradeUpdateMessage) -> str:
    """ADR 7's dedupe key for a fill (`execution_id`), generalized to every tracked event type."""
    if message.execution_id is not None:
        return message.execution_id
    return f"{message.order.id}:{message.event}:{message.timestamp.timestamp()}"


class TradeUpdatesConsumer:
    def __init__(self, *, intake: EventIntakeService) -> None:
        self._intake = intake

    def handle_message(self, raw: dict[str, Any]) -> IntakeResult | None:
        """Validate, dedupe-key, and hand `raw` to the shared intake path. `None` for an untracked
        Alpaca event."""
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
        """The real, network-touching wiring onto `TradingStream`; not exercised by unit tests.
        Blocking. `tenacity` retries with exponential backoff; a gap past `stale_after` logs an
        operational alert rather than retrying silently forever (ADR 22, NFR-6)."""
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
