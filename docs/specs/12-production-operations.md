# S12 — Production Operations & Performance: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: NFR-17, NFR-18 (this spec's own new requirements) plus a cross-cutting
efficiency pass over S0–S11
Depends on: S0 (foundation — jobs, event intake), S1–S11 (this spec adds no new business logic; it
is the operational layer beneath all of them)
Consumed by: nothing — this is infrastructure/ops, the outermost non-functional layer

This spec closes six gaps found in a production/real-time-efficiency review of the completed
S0–S11 specs: no indexing strategy, no observability/alerting mechanism, sequential per-customer
batch jobs, no real-time push outside S11, no caching for hot shared reads, and no stated latency/
throughput targets or load-test plan.

## 1. Purpose

Every prior spec is correct about *what* the system must do (verified by a full FR/NFR cross-check
before this spec was written). This spec is about *how well* it does it once real data volume and
real concurrent users exist — the difference between a design that is correct on day one and one
that stays correct and responsive as the ledger grows monotonically (ADR 1's own stated consequence)
and the customer base grows with it.

## 2. Non-goals

- Any new business logic, schema beyond indexes, or requirement — this spec is purely operational.
- Multi-region/high-availability architecture — out of scope for NFR-11's six-week timeline, an
  explicit future consideration, not designed here.
- Exact numeric alert thresholds and dashboard layouts — left to implementation-time tuning against
  real traffic; this spec fixes the *mechanism* (§4), not every threshold value.

## 3. Indexing strategy

**The rule, stated once so it doesn't need restating per table**: every foreign key gets an
explicit supporting index (Postgres does not create one automatically for a FK column), and every
`WHERE`/`ORDER BY` access pattern named in another spec's own pseudocode gets a composite index
added in that table's migration, at the time that table is created — never discovered and bolted on
ad hoc in production later. A new query pattern found after the fact requires a new migration, the
same discipline S1 §8 already applies to `CHECK` constraints and grants.

Initial index set, each cited back to the spec and query pattern that requires it:

| Table | Index | Cited from |
| --- | --- | --- |
| `account` | `(customer_id, role)` | every cash-policy/balance query, S1 §5 |
| `posting` | `(account_id)` | S1's balance-summing queries |
| `journal_entry` | `(effective_date)`, `(recorded_at)` | S1/ADR 1's bitemporal range queries |
| `daily_close` | `(security_id, market_date, recorded_at DESC)` | S4 §4's "latest confirmed close for a date" lookup |
| `order` | `(customer_id, status)` | S3 §6's order list/status queries |
| `order_event` | `(order_id, seq)` | S3's fold-by-seq projection rebuild |
| `tax_lot` | `(customer_id, security_id, acquired_at)` | S5 §4's FIFO ordering |
| `reconciliation_break` | `(status, opened_at)` | S7 §7's aged-break-list query |
| `chat_message` | `(session_id, created_at)` | S11 §6's message history |
| `admin_audit_log` | `(target_customer_id, recorded_at)` | foundation spec §7.2's adviser-action audit lookups |
| `fee_accrual` | already covered by its `UNIQUE (customer_id, accrual_date)` | S10 §3.3 |
| `inbound_event` | already covered by its `UNIQUE (source, source_event_id)` | foundation spec §6 |

Every index above is added in the same migration as the table it belongs to — for the tables already
specified in S1–S11, this is a small addendum to each of those migrations, not a new standalone
migration touching tables another spec owns.

## 4. Observability and alerting (ADR 20)

Application Insights auto-instruments the Flask app, SQLAlchemy queries, and every outbound HTTP call
(Alpaca, Plaid, Stripe, OpenAI) with minimal code — a middleware/SDK integration in `app/extensions.py`
(per `backend/CLAUDE.md`'s existing convention for where extension instances live), not a design this
spec needs to invent per-integration.

**The mapping this spec exists to produce** — every "should alert" statement already written
elsewhere in this design, now a concrete Azure Monitor Alert rule:

| Condition (already named elsewhere) | Source | Alert rule |
| --- | --- | --- |
| A `job_run` row missing for an expected trading day/month | foundation spec §9 | Log-based alert: query for absence of an expected daily/monthly row past its expected completion time |
| A `job_outbox` row reaches `dead_letter` | foundation spec §9 | Metric alert on `dead_letter` count > 0 |
| `SnapshotService.cross_check` fails (ADR 6/S6 §6) | S6 §6 | Custom event/exception tracked by Application Insights, alert on any occurrence — this is a tamper-detection alarm, zero tolerance |
| A `reconciliation_break` opens with `break_type = position_mismatch` (FR-32's own live-fire condition) | S7 §5 | Metric alert on any new row, since v1 has no materiality threshold (S7 §12) |
| An `app_bypass`-role connection is used outside a job/worker process | ADR 17 | Database-level: a periodic query asserting the `app_bypass` role's active connections originate only from known job/worker hosts; alert on any exception |
| `ChatUsageLimiter`'s daily cap rejects an unusually high fraction of a customer's requests (S11 §9) | S11 §5.2 | Metric alert — a signal of either abuse or a cap set too low, not distinguished automatically; routed to on-call for triage either way |
| A dunning charge reaches `exhausted` (S10 §5) | S10 §5 | Metric alert — a customer-visible failure state that should also prompt an operational look, not only the customer's own view |

Each rule routes to a single named Azure Monitor action group in v1 (no per-severity routing tiers —
YAGNI until there's an on-call rotation large enough to need one).

## 5. Job batching and parallelization

Every batch job that loops `for each customer` (S9's `MonthlyRebalanceJob`, S10's
`DailyFeeAccrualJob`/`MonthlyFeeChargeJob`, S7's `MorningReconciliationJob` cash-comparison pass)
is revised from a plain sequential loop to:

- **Within one job execution**: a bounded concurrent worker pool (Python's `concurrent.futures.
  ThreadPoolExecutor`, since this work is I/O-bound — database and provider HTTP calls, not CPU-bound
  computation) processes multiple customers' work concurrently, with a pool size set conservatively
  against the database's connection limit (each worker holds its own `UnitOfWork`/connection).
- **Across job executions, if needed at larger scale**: Azure Container Apps Jobs' own `parallelism`
  setting runs multiple replicas of the same job, each given a shard index via an environment
  variable (`JOB_SHARD_INDEX`, `JOB_SHARD_COUNT`), partitioning customers by
  `hash(customer_id) % JOB_SHARD_COUNT == JOB_SHARD_INDEX`. This is horizontal scaling **without** a
  broker or queue — each shard is an independent, self-contained execution, composing with ADR 13's
  core rejection of a message broker rather than reopening it.
- **Per-shard, per-worker failure isolation**: one customer's processing failure (e.g., a provider
  timeout during their fee charge) is caught and logged per-customer, never aborting the whole job
  execution — a single bad case must not prevent every other customer's job from completing within
  the window.

## 6. Real-time push implementation (ADR 20)

ADR 20 decided SSE + Redis Pub/Sub; this section is the concrete wiring so S8's routes (§5.1 of
`docs/specs/08-surfaces.md`) have something exact to call rather than a restated decision.

- **`GET /api/v1/events/stream`** (customer) and **`GET /api/v1/admin/events/stream`** (adviser) —
  long-lived SSE connections, `@login_required` + `@requires_ownership`/`@requires_role` exactly like
  any other route (foundation spec §7.2). One connection per open session; the API process holds it
  open and streams `event:`/`data:` frames as they're published.
- **Publish side**: any service that already posts a domain fact publishes a small notification
  immediately after its commit — never inside the same transaction (foundation spec §5's no-I/O-in-
  a-transaction rule extends here: a Pub/Sub publish is an external call, not a database write, and
  must not risk holding a transaction open). Concretely: `OrderService` (S3) publishes on a fill/
  terminal-state `order_event`; `KycService`/`AccountApprovalService` (S2) publish on a status
  change; `ReconciliationService` (S7) publishes on opening a `reconciliation_break`.
- **Channel naming**: `customer:<customer_id>:events` for customer-scoped facts, `adviser:events` for
  the adviser-facing break queue — a customer's channel is never subscribed to by anything but that
  customer's own SSE connection(s), enforced by the same ownership check the SSE endpoint itself
  requires at connection time.
- **Message shape**: `{ event_type, entity_id, summary }` — a small pointer, not the full entity
  payload; the client's reaction to receiving one is to re-fetch the relevant `GET` endpoint (§3–§4
  of `docs/specs/08-surfaces.md`), never to trust the pushed payload as authoritative. This keeps the
  push path simple and means a schema change to, say, `order` never requires a corresponding change
  to the notification message shape.
- **Fanout mechanics**: `PUBLISH customer:<id>:events <message>`; every API replica subscribes to
  every channel its currently-connected clients care about (`SUBSCRIBE` on connection open,
  `UNSUBSCRIBE` on disconnect) — a message published while no replica holds that customer's
  connection is simply not delivered to anyone, which is the accepted, documented behavior (§9 edge
  case 3): the next poll or page load still reads live state directly.

## 7. Caching

A Redis read-through cache for exactly two read patterns — chosen because both are safely
re-derivable, immutable-or-slowly-changing, and never the authoritative record for a customer-facing
financial figure:

- **`daily_close`**, once `status = 'confirmed'`: cache key includes `(security_id, market_date,
  recorded_at)` — per ADR 1's bitemporal versioning, a corrected close is a **new** row with a new
  `recorded_at`, hence a new cache key, never an invalidation of an old one. No TTL needed; a
  confirmed close for a past date never changes under its own key.
- **`target_weight`**: a short TTL (e.g. 5 minutes) — changes rarely, and monthly-cadence rebalancing
  (S9) tolerates a few minutes of staleness with zero correctness impact, since the drift-evaluation
  window is measured in weeks, not seconds.

**Explicitly not cached**: anything cash-, balance-, or order-state-related. Those remain live reads
against RLS-guarded tables, now properly indexed (§3) — correctness for money-moving state matters
more than shaving milliseconds off a read that's already fast once indexed, and caching it would
reintroduce exactly the kind of "is this figure live or stale" ambiguity ADR 6 already spent real
design effort eliminating for return figures.

## 8. Latency/throughput SLOs and a load-test plan

| Surface | Target |
| --- | --- |
| Read endpoints (`GET /valuation/*`, `/orders`, `/statements`, etc.) | p95 < 300ms, p99 < 800ms |
| Write endpoints (`POST /orders`, `/deposits`, `/withdrawals`) | p95 < 500ms, excluding the async outbox call to a provider |
| `MorningReconciliationJob` | completes before 06:00 America/New_York, ahead of market open |
| `DailyValuationJob` | completes within 2 hours of market close |
| SSE push latency (event committed → client receives it) | < 2 seconds, p95 |

**Load-test plan**: a tool (e.g. k6 or Locust) exercises the read-heavy endpoints and the batch
jobs' per-customer loop against a staging environment sized to a stated target customer count,
gating go-live rather than running on every PR (a full load test on every commit is disproportionate
cost for a six-week build; it belongs before a production cutover, and again before any change that
touches an indexed query pattern or a batch job's core loop).

## 9. Edge and corner cases

1. **A Redis outage** — the two cached reads (§7) fall through to Postgres directly on a cache miss
   or connection failure; nothing in this design treats Redis as required for correctness, only for
   speed and for SSE fanout (whose failure degrades to "no push, next poll still works," per ADR 20).
2. **A job shard fails entirely** (§5) while others succeed — the `job_run` row for that shard
   records its own failure independently; the missing-run alert (§4) fires for that shard's slice of
   work specifically, not masked by other shards' success.
3. **An SSE connection drops mid-session** (network blip, client backgrounded) — the client
   reconnects and the next poll/page-load reads live state directly; no message queue or replay
   buffer is needed, since nothing published over Pub/Sub was ever the only record of a fact (ADR 20).
4. **A cached `target_weight` read during the exact window a rebalance run updates it** — the
   5-minute TTL means at most one drift evaluation cycle could read a slightly stale target; given
   rebalancing itself runs monthly, this has no material effect and is an accepted, bounded staleness
   window, not a correctness bug.
5. **Concurrent job shards touching the same customer** (a sharding bug assigning one customer to two
   shards) — the underlying idempotency guarantees already required by every job (foundation spec
   §9) mean a double-processed customer produces a duplicate-write rejection (e.g. `fee_accrual`'s
   `UNIQUE (customer_id, accrual_date)`), not a double-charged or double-accrued outcome — sharding
   adds a performance dimension, it does not weaken any correctness guarantee already designed.

## 10. Testing strategy

- **Unit** — the sharding hash function's even distribution across a representative customer-ID set.
- **Integration** — each new index actually gets used by its target query (`EXPLAIN ANALYZE`
  assertions in a test, not just presence of the index definition); the cache-miss fallback path for
  both cached reads; the per-customer failure isolation inside a job's worker pool (one simulated
  failure must not abort the batch).
- **Load** — the k6/Locust suite itself, run against staging per §8, not part of the standard
  `uv run pytest` CI gate (too slow/costly to run on every PR).

## 11. Open parameters (not blocking this spec)

- Exact alert-routing tiers (a single action group in v1, per §4) — revisit once there's an on-call
  rotation large enough to need severity-based routing.
- The load-test target customer count and the exact SLO numbers in §8 — reasonable starting points,
  tunable once real usage data exists.
- Multi-region/HA — explicitly deferred, consistent with NFR-11's timeline.
