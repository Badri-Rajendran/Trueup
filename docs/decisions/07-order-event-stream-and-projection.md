# 7 — Order event stream with projection; execution-ID dedupe; missed-event backstop owned by S7

## Status

Accepted

## Context

FR-8 requires a full order lifecycle (submitted → partially filled → filled). FR-9 requires fills
to arrive by webhook and be processed idempotently — replaying a fill webhook must not double
positions (live-fire scenario 4). FR-29 requires correctly representing a book left mid-flight
overnight by partial fills. Two separate problems live here and must not be conflated: (a) how
order state is represented and kept consistent with the ledger's append-only posture, and (b) what
happens when a fill webhook is *not* delivered at all (silent under-count), as opposed to
delivered twice (the case the brief's live-fire test actually exercises).

## Decision

### Order state representation

`order_event` (order_id, seq, type, payload, execution_id, recorded_at) is the append-only source
of truth. The `order` row is a **rebuildable projection** carrying status, cumulative filled
quantity, and average price for fast queries — the same append-only-truth-plus-projection shape as
ADR 1 and ADR 6. Invariant: `assert projection == fold(events)`; rebuild-from-events is the
recovery path if it ever fails.

States: `draft → awaiting_approval → approved → submitted → accepted → partially_filled → filled`,
with `rejected` / `canceled` / `expired` as terminals.

- `awaiting_approval` (FR-10, above the configurable threshold) places a **cash hold** — without
  it, the same dollars could be committed to two pending orders. This is the `- holds` term in
  ADR 5's `investable` formula.
- `partially_filled` is not one transition but **N fill events**, each carrying its own execution
  ID, settlement date, tax lot, and lot-designation window (ADR 4).

### Deduplication key

Inbound fill events are deduped on the broker's **execution/fill ID**, never the order ID. A
partial fill produces multiple fills per order; keying on order ID would silently swallow every
fill after the first.

### Missed-event backstop ownership

Detecting a fill that was **never delivered** (as opposed to delivered twice) is explicitly **not**
S3's responsibility. The custodian file is the backstop, and break detection with aging already
belongs to S7 (FR-31). S3 does not get its own polling loop or reconciliation pass against the
broker.

## Consequences

- Live-fire scenario 4 (replay a fill webhook) is satisfied directly by the execution-ID dedupe key
  with no additional machinery.
- A missed fill is caught by S7's morning reconciliation, not same-day — accepted, since the brief's
  reconciliation cadence is explicitly the daily custodian file (FR-30), and a second, faster
  reconciler inside S3 would duplicate S7's break-detection machinery with its own independent
  failure modes (a duplicated system is not a safer one; it is two things that can each be wrong).
- Any product requirement for *same-day* detection of a missed fill is a scope change to S7's
  cadence, not a reason to add a second reconciler in S3 — must be raised explicitly if it arises.

## Alternatives considered

- **Order ID as the dedupe key.** Rejected outright: incompatible with partial fills, which the
  brief requires supporting (FR-8, FR-29).
- **A periodic poll-the-broker reconciler inside S3** as a same-day backstop for missed webhooks.
  Considered, but rejected as scope creep into S7's responsibility — it would duplicate break
  detection and aging that S7 already owns, creating two independently-failing sources of truth for
  the same question ("did this fill actually happen").
- **Webhook plus terminal-state read-back** (fetch the order from the broker whenever a terminal
  webhook arrives, to confirm quantity). Rejected for the same reason: it only triggers when *some*
  webhook arrives, so an order whose final event is never delivered at all is still missed until the
  custodian file catches it — no better than the chosen design, with added complexity.
