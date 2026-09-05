# 22 — Alpaca fills arrive over a `trade_updates` websocket, not an HTTP webhook

## Status

Accepted

## Context

S3 §6 specifies `webhooks/alpaca_fills.py` as the receiver for order and fill events, and S0 §6
routes every inbound signal — "broker fills, settlement confirmations, deposit returns, dividends,
splits, price corrections, custodian file rows, daily closes, and KYC verdicts" — through one
`inbound_event` intake path fed by HTTP webhook controllers.

That shape assumed HTTP webhooks were available for broker events. They are not, under the product
[ADR 21](21-alpaca-paper-trading-not-broker-api.md) chose. Alpaca's **Broker API** has HTTP webhook
events; the **Trading API** (paper and live alike) does not. It delivers order lifecycle and fill
events only as a `trade_updates` stream over a websocket at `wss://paper-api.alpaca.markets/stream`,
authenticated with the same API key pair, carrying `new`, `fill`, `partial_fill`, `canceled`,
`expired` and `rejected` events with their `execution_id`.

So S3's webhook controller cannot be built as written. There is no endpoint Alpaca would ever call.
This was found while planning the S0–S4 implementation, not while writing S3, which is why neither
spec records it.

Non-negotiable #2 constrains the alternatives: "Polling is a fallback strategy, not the design."

## Decision

**Broker events reach Trueup through an always-on websocket consumer, and that consumer writes into
the same `inbound_event` table every other inbound signal uses.** The transport changes; nothing
else does.

- `app/integrations/alpaca/trade_updates_stream.py` holds a long-lived authenticated websocket
  subscription to `trade_updates`, run as its own process (`flask jobs alpaca-stream`), deployed as
  an always-on Container Apps revision — the same deployment shape S0 §9 already defines for the
  outbox worker, not a new pattern.
- Each message is validated by a Pydantic model before any service sees it (S0 §6's untrusted-input
  rule, unchanged), then inserted into `inbound_event` with `source = 'alpaca'` and
  `source_event_id = execution_id` for fills — **the dedupe key ADR 7 already mandates**, never the
  order ID. The `UNIQUE (source, source_event_id)` constraint remains the single dedupe mechanism.
- The insert enqueues a `job_outbox` row and issues `NOTIFY job_outbox_ready` in the same
  transaction, exactly as S0 §6 step 3 specifies. Downstream processing, folding by `seq`,
  projection, and hold release are all completely unchanged.
- `signature_verified` is set `true` on the basis of the authenticated TLS websocket session itself:
  the stream is opened by Trueup to Alpaca's own host and authenticated with Trueup's API key, so
  there is no unauthenticated third party who could inject a message and no per-message signature to
  verify. This differs from Stripe/Plaid webhooks, where an unauthenticated public endpoint makes
  per-message signature verification the only trust anchor. Recorded explicitly so the column's
  meaning is not silently different across sources.
- **Reconnection is not optional and not silent.** The consumer reconnects with `tenacity`
  exponential backoff, and a disconnection longer than a configurable threshold raises an
  operational alert rather than being logged and forgotten — an unnoticed dead stream is exactly the
  failure NFR-6's honest-degradation stance exists to prevent.
- S7's morning reconciliation remains the backstop for anything the stream missed while
  disconnected, per ADR 7's existing division of responsibility. That is what makes a dropped
  websocket a recoverable condition rather than permanently lost fills.

## Consequences

- S3 §6's `webhooks/alpaca_fills.py` line is superseded by this ADR; S3 gains a pointer to it.
  Plaid and Stripe webhook controllers are unaffected and remain HTTP.
- One more always-on process to deploy and monitor, alongside the outbox worker. Its liveness is a
  container health check, not a `job_run` row — S0 §9 already draws that distinction for
  continuously-running processes.
- The `FakeBrokerAdapter` emits the identical event shapes into the identical intake path, so the
  S3 contract suite exercises fill/reject/cancel/expire handling with no live Alpaca connection.
  A test never opens a websocket.
- Polling is retained strictly as S7's morning reconciliation backstop, which is a reconciliation
  feature in its own right (non-negotiable #4), not a fill-delivery mechanism — non-negotiable #2 is
  satisfied rather than worked around.

## Alternatives considered

- **Poll Alpaca's orders/activities endpoints on a short interval.** Rejected: directly contradicts
  non-negotiable #2, and adds fill latency proportional to the poll interval for no benefit, since
  the stream is available and authenticated with credentials the system already holds.
- **Migrate to Broker API to obtain real HTTP webhooks.** Rejected here for the same reason ADR 21
  rejected it: an open-ended onboarding wait incompatible with NFR-11's timeline. This ADR is a
  direct consequence of that decision, not an independent one.
- **Have the websocket consumer call `EventIntakeService` synchronously and skip `inbound_event`.**
  Rejected: it would give broker fills a second, privileged intake path with its own dedupe
  behaviour, which is precisely the "one dedupe implementation per handler" shape `architecture.md`
  and S0 §6 exist to prevent.
