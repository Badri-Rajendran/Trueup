# 20 — Azure Application Insights for observability; SSE + Redis Pub/Sub for real-time push

## Status

Accepted

## Context

A production/real-time-efficiency review of the completed S0–S11 specs found two unaddressed gaps
this ADR closes. First: every prior spec correctly names a failure condition that "should raise an
operational alert" (a missing `job_run`, a dead-lettered `job_outbox` row, ADR 6/S6's `cross_check`
failure, an `app_bypass` role misuse) but none specify the mechanism that turns that into an actual
page — "should alert" and "does alert" are not the same thing, and only the first existed. Second:
every customer/adviser-facing route (S8) is REST GET/POST only; an order fill, a KYC verdict, or a
new reconciliation break is invisible until the next poll or page load, in tension with the brief's
own "watching your orders land at the broker" live-fire framing. S11 solved this for the chat
feature alone (SSE); nothing solved it for the surfaces that matter more.

## Decision

### Observability: Azure Application Insights + Azure Monitor

No new vendor relationship — the stack is already committed to Azure (root `CLAUDE.md`). Application
Insights auto-instruments Flask, SQLAlchemy, and outbound HTTP calls (Alpaca/Plaid/Stripe/OpenAI)
with minimal code, giving traces, metrics, and logs in one place rather than three. Every existing
"should alert" statement across S0–S11 becomes a concrete **Azure Monitor Alert rule** with a named
action group (email/SMS/webhook/PagerDuty) — `docs/specs/12-production-operations.md` is where each
one is enumerated and mapped, not restated as prose a second time.

### Real-time push: Server-Sent Events + Redis Pub/Sub fanout

The same primitive S11 already uses (SSE), extended to S8's customer/adviser surfaces. A domain event
(a fill posted, a KYC verdict recorded, a reconciliation break opened) publishes to a Redis channel
keyed by customer ID; whichever stateless API replica currently holds that customer's open SSE
connection forwards the message, others ignore it. No new infrastructure component — Redis is already
in the stack for sessions and rate-limit counters (ADR 13/15); this is the same instance, a different
use.

**This does not reopen ADR 13/15's "Redis never holds financial state" rule.** A published Pub/Sub
message is an ephemeral notification *about* a fact that has already committed to Postgres — it is
never the fact itself, and it is never read back as a source of truth. If a message is dropped (a
replica restart, a momentary Redis blip), nothing is lost except a few seconds of UI latency: the
customer's next poll or page load still reads the authoritative state directly from the database,
exactly as it does today. The rule this ADR must not violate is "Redis never holds financial state,"
not "Redis is never used for anything financial-adjacent" — a transient notification about a state
change is not the state.

## Consequences

- `docs/specs/12-production-operations.md` carries the concrete alert-rule mapping and the SSE/
  Pub/Sub wiring detail; this ADR records only the vendor/transport choice and why it doesn't
  conflict with earlier decisions.
- Every future sub-project that introduces a new "should alert" condition adds a row to that same
  mapping table, rather than inventing its own alerting mechanism.
- A customer/adviser session with no active SSE connection (app closed, tab not open) simply doesn't
  receive the push — the next page load reads live state as normal, so nothing is silently lost, only
  the "instant" quality of the notification.

## Alternatives considered

- **A dedicated third-party APM (Datadog, Sentry).** Genuinely richer dashboards and error-tracking
  UX in some teams' experience, but adds a new vendor relationship and a separate bill on top of the
  already-committed Azure stack — redundant with what Azure Monitor already provides, for no stated
  need this six-week build has that Azure-native tooling can't meet. Rejected.
- **WebSocket** for real-time push. Bidirectional, but nothing on these surfaces needs the client to
  push data back through the same channel — every use case here is one-way, server-to-client status
  notification. WebSocket costs more to operate correctly (sticky connections, ping/pong keep-alive
  across Azure Container Apps replicas) for capability this design never uses. Rejected in favor of
  SSE, consistent with S11's own already-accepted choice.
- **Short-interval polling, no new transport.** Zero new infrastructure, but continuous API load that
  scales with every active customer regardless of whether anything actually changed, and doesn't
  match the brief's own live-fire framing of near-instant feedback. Rejected.
