# S3 — Orders & Custody: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-7–10, FR-29, FR-38
Depends on: S1 (ledger — a fill posts a `trade_buy`/`trade_sell` entry; the approval hold uses S1
§5's `holds(customer)` contract), S2 (funding/account-approval gates must both be `approved` before
an order can be placed)
Consumed by: S5 (a fill is the event that opens/consumes a tax lot), S9 (rebalance-generated orders
flow through this same service, not a parallel path)

## 1. Purpose

Place real (paper) orders with a full lifecycle, receive fills by webhook and process them
idempotently (FR-8–9, live-fire scenario 4), gate trades above a threshold on explicit approval
(FR-10), correctly represent a book left mid-flight overnight by partial fills (FR-29), and release an
approval hold the instant an order reaches any terminal non-filled state (FR-38) — a stranded hold
that never releases understates available cash indefinitely, exactly the defect FR-38 exists to rule
out.

## 2. Non-goals

- Which portfolio/target weights an order is generated *from* — that's S9's decision; this spec
  accepts an order request from any caller (customer or S9) and treats it identically once accepted.
- Tax lot consumption on a sell fill — S5.
- The missed-fill-webhook backstop — explicitly S7's job, not S3's, per ADR 7's own division of
  responsibility (repeated here because it is the single most likely scope-creep point for this spec).

## 3. Schema

### 3.1 `order`

The rebuildable projection (ADR 7) — `assert projection == fold(order_event)` is the standing
invariant; this table is a fast-path cache, not a second source of truth.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | Trueup's own order ID |
| `customer_id` | uuid, FK | |
| `security_id` | uuid, FK | |
| `side` | enum | `buy` \| `sell` |
| `quantity_requested` | `Units` | |
| `status` | enum | see §4's state list |
| `filled_quantity` | `Units` | cumulative, folded from fill events |
| `average_fill_price` | `Price`, nullable | |
| `client_order_id` | text, unique | **deterministic**, derived from `order.id` — never regenerated on retry (§6.2) |
| `created_at`, `updated_at` | timestamptz | |

### 3.2 `order_event`

Append-only source of truth (ADR 7).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `order_id` | uuid, FK | |
| `seq` | int | per-order monotonic sequence; folding tolerates gaps (foundation spec §10 case 4) |
| `event_type` | enum | `submitted`, `accepted`, `fill`, `rejected`, `canceled`, `expired` |
| `execution_id` | text, unique, nullable | set only on `fill` events — **the dedupe key** (ADR 7), never the order ID |
| `payload` | jsonb | raw broker event |
| `recorded_at` | timestamptz | |

### 3.3 `approval_hold`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `order_id` | uuid, FK, unique | |
| `customer_id` | uuid, FK | |
| `amount_money` | `Money` | the notional held against `investable` (S1 §5, ADR 5) |
| `status` | enum | `active` \| `released` |
| `released_at` | timestamptz, nullable | |
| `release_reason` | enum, nullable | `approved_and_submitted` \| `rejected` \| `canceled` \| `expired` — FR-38 requires this be set for **every** terminal non-filled path, not just an explicit customer rejection |

## 4. Order state machine (ADR 7)

```
draft → awaiting_approval → approved → submitted → accepted → partially_filled → filled
                 │              │           │           │              │
                 └─ rejected ───┴─ canceled ┴─ expired ──┴──────────────┘   (terminals)
```

- **`draft → awaiting_approval`**: only when the order's notional exceeds the configurable approval
  threshold (default `$10,000`, `ORDER_APPROVAL_THRESHOLD_USD` setting — FR-10). Below threshold,
  `draft → approved` is immediate, no hold needed for the approval step itself (a hold is still
  needed before submission either way, per the next point).
- **`approved → submitted`**: the transition into `submitted` happens **only after the outbox's call
  to Alpaca actually succeeds** (foundation spec §10 case 3 — the seam that spec flagged for S3 to
  resolve explicitly). `OrderService` persists the intent plus a `job_outbox` row, commits, and the
  outbox worker's successful broker response is what fires `submitted`'s `order_event` — an order
  never shows `submitted` while the broker never received it.
- **`submitted → accepted → partially_filled* → filled`**: driven entirely by inbound webhook events
  through the foundation spec's shared intake path, folded by `seq`.
- **Terminal non-filled states** (`rejected`, `canceled`, `expired`): **FR-38** — the instant any of
  these is folded, `ApprovalHoldService.release(order_id, reason)` fires in the same transaction as
  the `order_event` insert. This is not a follow-up job; a hold and the event that ends its reason for
  existing commit together, so there is no window where a stranded hold could understate available
  cash even momentarily longer than necessary.

`awaiting_approval` and `approved`-but-not-yet-`submitted` both hold (§3.3) — this is the `- holds`
term in ADR 5's `investable` formula. The hold write happens inside the same per-customer cash-lock
transaction the foundation spec §10.1 requires for every cash-consuming operation (order hold,
withdrawal, fee charge) — evaluated once here, generalized there.

## 5. Deduplication and idempotency

- **Fill events dedupe on `execution_id`** (ADR 7) — never `order_id`. A partial fill produces many
  fills per order; each is a distinct `order_event` row.
- **`client_order_id` is deterministic**, derived from `order.id` at order creation and never
  regenerated on a retried submission (foundation spec §10 case 2) — a network timeout on the
  `POST` to Alpaca can be safely retried with the same `client_order_id`, and the broker's own
  idempotency (if it dedupes on that field) or the outbox's own retry-with-backoff handles the rest;
  ambiguity that survives both is caught the next morning by S7, per ADR 7's explicit division.
- **NFR-14**: `POST /orders` itself accepts a customer-supplied `Idempotency-Key`, distinct from
  `client_order_id` — the former prevents a duplicate *order* from a double-click; the latter
  prevents a duplicate *broker submission* of the same already-created order. Two different
  problems, two different keys, not conflated.

## 6. API contract

- `POST /api/v1/orders` → create an order (`Idempotency-Key` required, NFR-14).
- `POST /api/v1/orders/<id>/approve` → customer approves an `awaiting_approval` order (FR-10);
  `@requires_ownership`.
- `GET /api/v1/orders`, `GET /api/v1/orders/<id>` → status/history.
- `webhooks/alpaca_fills.py` → through the shared intake path (foundation spec §6); no bespoke
  dedupe logic beyond what that path already provides.

## 7. Edge and corner cases

1. **A fill arrives before its order's `accepted` event** (foundation spec §10 case 4) — folding by
   `seq` tolerates the reordering; the projection still ends up correct once both events exist.
2. **An order approved but the customer's account is subsequently suspended before submission** —
   `OrderService` re-checks S2's KYC/account-approval gates immediately before the outbox call, not
   only at order-creation time; a gate that closed in between blocks submission and releases the
   hold with reason `rejected`.
3. **A partial fill leaves the book mid-flight overnight** (FR-29) — `partially_filled` is a stable,
   correctly-representable state, not a transient one the system assumes resolves same-day; S4's
   valuation reads `filled_quantity` as of end-of-day regardless of whether the order later completes.
4. **Two orders for the same customer placed within the same cash-lock window** — serialized by the
   foundation spec's per-customer lock (§10.1), not by any mechanism local to this spec.
5. **A `rejected`/`canceled`/`expired` event for an order with no active hold** (e.g. it was already
   released by an earlier event, or never held because it was below threshold) — `ApprovalHoldService.
   release` is idempotent: releasing an already-`released` or nonexistent hold is a no-op, never an
   error that could block folding the event itself.
6. **Order-approval threshold exactly at the boundary** — `> threshold` requires approval, `<=
   threshold` does not; stated explicitly so the boundary condition itself has a defined answer
   rather than being left to whichever comparison operator gets typed first.

## 8. Testing strategy

- **Unit** — the state machine's transition table (every legal and illegal transition), the
  threshold boundary condition, hold-release idempotency.
- **Integration** — `assert projection == fold(order_events)` as a property-based test over random
  valid event sequences (including reordered `seq`); the hold-release-in-same-transaction guarantee
  (kill the transaction mid-way, assert neither the event nor the release persisted — not one without
  the other).
- **API** — authn/authz/ownership on approve; the idempotency-replay path for `POST /orders`.
- **Contract** — `BrokerPort`'s real (Alpaca) and fake adapters against the identical fill/reject/
  cancel/expire event shapes.

## 9. Open parameters (not blocking this spec)

- `ORDER_APPROVAL_THRESHOLD_USD` (default $10,000) — a tunable setting, adjustable per the same
  pattern as every other threshold in this design.
- Whether a rejected/expired order should notify the customer proactively (push/email) versus only
  being visible on next view — an S8 UX decision, not this spec's.
