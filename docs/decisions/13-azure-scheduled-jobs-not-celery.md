# 13 — Scheduled and asynchronous work: Azure Container Apps Jobs + Postgres outbox, not Celery/Redis

## Status

Accepted

## Context

Daily valuation (S4), morning reconciliation (S7), monthly rebalance (S9), and daily fee accrual /
monthly charge / dunning retries (S10) all need something to run them on a schedule; webhook intake
(architecture.md) needs something to process events asynchronously after the webhook responds. No
ADR had decided this, and the choice is genuinely load-bearing: it decides where financial work
lives while in flight, and how failures in that layer are detected.

## Decision

**Azure Container Apps Jobs** (cron, defined in infrastructure-as-code) run the scheduled work.
**A Postgres outbox** (`job_outbox`), drained with `SELECT ... FOR UPDATE SKIP LOCKED`, carries
asynchronous retryable work (webhook post-processing, Stripe dunning retries). **No message broker.**

- `app/jobs/` holds one plain class per job, each exposed as a Flask CLI command
  (`flask jobs reconcile`). A job class imports no scheduler, so it is unit-testable with zero
  infrastructure and the exact same entrypoint runs in production (via Azure's cron), in CI, and on
  a developer's machine (`make job-reconcile`) — one code path, not one path for production and a
  stand-in everywhere else.
- `job_run(job_name, market_date, started_at, completed_at, status, error)`,
  `UNIQUE(job_name, market_date)`, records every execution. The system can assert a job ran for a
  given trading day rather than inferring it from the absence of an alert — extending NFR-6's
  honest-degradation stance to the jobs layer itself.
- `pg_try_advisory_lock(hashtext(job_name))` prevents an Azure retry or an overlapping manual
  invocation from double-running a job.
- Every job is required to be idempotent and resumable — safe to run twice, safe to be killed
  mid-execution — since Azure can retry a failed job and a container can be evicted mid-run.
- Redis remains in the stack, demoted to sessions (ADR 15) and Flask-Limiter rate-limit counters
  only. It never holds financial work in flight.

### Hot-path draining: an always-on worker with `LISTEN`/`NOTIFY`, not cron, for webhook-triggered work

A design review found that draining `job_outbox` on the same cron mechanism as daily/monthly batch
jobs mismatches FR-9 ("receive fills by webhook... process idempotently") and general production
expectations: cron's practical scheduling granularity means a fill, KYC verdict, or Stripe event
could sit unprocessed for up to a scheduling interval, which is fine for a once-daily reconciliation
and a real defect for "process this promptly."

- **Batch jobs stay exactly as decided above** — Azure Container Apps Jobs (cron) for daily
  valuation, morning reconciliation, monthly rebalance, and daily fee accrual/monthly charge.
- **One always-on Container Apps worker revision** is added, whose only responsibility is draining
  `job_outbox`. It blocks on Postgres `LISTEN job_outbox_ready`; the webhook controller's insert into
  `job_outbox` issues `NOTIFY job_outbox_ready` in the same transaction, so the worker wakes and
  begins draining within milliseconds instead of waiting for the next cron tick.
- This does **not** reopen the Celery question: Postgres remains the sole source of truth for
  outstanding work — there is still no broker, no second system of record for "did this get
  processed." The worker is a thin, stateless consumer of a durable table, not a queue of its own.
  Its liveness is a container health check, not a `job_run` row — a different, correct mechanism for
  a continuously-running process versus a scheduled batch execution (see
  `docs/specs/0-backend-foundation-design.md` §9's `job_run.cadence` distinction).

## Consequences

- Local development and CI exercise the identical job entrypoint production uses — no separate
  "test scheduler" to keep in sync with the real one.
- A missed or failed schedule is a queryable, alertable `job_run` gap, not a silent absence.
- Fits the Azure deployment target already pinned in root `CLAUDE.md`, adding no new infrastructure
  component (no broker to provision, secure, patch, or back up).
- Async retries (webhook processing, dunning) share the same durability guarantee as the ledger
  itself — a Postgres row, not an in-memory or broker-held message that can be lost on restart.
- Every sub-project spec that names a scheduled job (S4, S7, S9, S10) implements it as a class under
  `app/jobs/` per this ADR's contract, rather than choosing its own scheduling mechanism.

## Alternatives considered

- **Celery + Redis broker + Celery Beat.** The default choice for Flask background work, and
  rejected specifically, not generically: a broker holding in-flight financial work is a second
  source of truth for "did this event get processed," next to the ledger — the same shape ADR 7
  already rejected for order reconciliation ("a duplicated system is not a safer one; it is two
  things that can each be wrong"). Redis is not durable by default, so an unflushed broker message
  can be silently lost on a restart. Celery Beat is a single process with no built-in high
  availability and no execution history of its own — if it dies silently, the morning reconciliation
  simply does not run, with nothing recording that fact, which is unacceptable for a regulated
  platform's daily control. Rejected.
- **In-process APScheduler with no broker.** Fewer moving parts and a single source of truth
  (Postgres), genuinely close to the accepted design — but scheduling inside the running API process
  requires a leader-election lock across replicas, and retry/backoff for async work would need to be
  hand-rolled rather than reusing Azure's own job execution and retry semantics. Rejected in favor of
  letting the platform (Azure) own scheduling and the database own durable async state, rather than
  the application owning both.
- **A hand-rolled cron container polling forever.** Functionally similar to the accepted design but
  without Azure's per-execution history, exit-code tracking, and native retry — would require
  rebuilding what Container Apps Jobs already provides. Rejected as unnecessary custom
  infrastructure.
- **Outbox draining on the same cron cadence as batch jobs (tight interval, e.g. every minute).**
  Considered for the hot-path draining question above. No new component, but accepts up to a
  scheduling interval of latency between a webhook arriving and the ledger reflecting it — a visible
  delay for a live-fire scenario like "watch your order land at the broker," and a real mismatch
  against FR-9's intent. Rejected in favor of the always-on `LISTEN`/`NOTIFY` worker.
- **Draining the outbox inline in the webhook request** (synchronously, or on a background thread in
  the same process, before returning). Lowest possible latency and no new component, but reintroduces
  exactly the risk this ADR's `job_outbox` design exists to prevent: a slow step could hold up the
  request, and a crash mid-processing loses the in-flight work with no durable retry record until a
  provider happens to retry the webhook. Rejected.
