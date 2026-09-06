# Backend Build Plan — S0 through S4

Date: 2026-09-05
Status: In progress — Waves −1, 0 and 1 complete; Waves 2–6 pending
Covers: `docs/specs/00-backend-foundation-design.md` through `docs/specs/04-valuation-and-returns.md`
Branch: `feature_backend_implementation`

This is a **delivery** plan, not a design spec. It says how the S0–S4 specs get built, in what
order, by whom, and what must be green before each step. What the system *does* lives in
`docs/specs/`; why it is shaped that way lives in `docs/decisions/`; what was decided, assumed or
cut, and when, lives in [`DECISION-LOG.md`](../../DECISION-LOG.md).

## 1. Decisions taken before any code

Six questions had to be answered before Wave 0 could start. Each is recorded here because the
waves below only make sense in light of them.

| # | Question | Decision |
| --- | --- | --- |
| 1 | No `.env` exists and every provider credential is blank | Build real adapters **and** fakes now. Contract tests parametrize over both and auto-skip the real side until keys land. Nothing inside the application is mocked. |
| 2 | S3 §6 specifies an HTTP fill webhook, but ADR 21 chose the Alpaca Paper Trading API, which has none | An always-on `trade_updates` websocket consumer feeding the **same** `inbound_event` intake path. Recorded as [ADR 22](../decisions/22-alpaca-trade-updates-websocket-intake.md). |
| 3 | S0 §7 specifies the auth *mechanism* but no spec enumerates login/register routes | Build the full auth surface inside S0, including adviser TOTP MFA. Without it nothing in S2–S4 is reachable end to end. |
| 4 | Tests need real PostgreSQL (S0 §11) | Docker Compose `postgres:16` + `redis:7`, on non-default host ports 5433/6380 so Trueup cannot collide with another project's database. |
| 5 | Four tables are referenced by FK or prose but never given a schema | Amend the owning specs **before** writing code, not invent tables inside an implementation. Became Wave −1. |
| 6 | S2 §3.3 requires `plaid_access_token` encrypted at rest; no mechanism was chosen | Azure Key Vault envelope encryption, [ADR 23](../decisions/23-key-vault-envelope-encryption.md). |

## 2. Waves

| Wave | Delivers | Agents | Status |
| --- | --- | --- | --- |
| −1 | Close spec gaps: four table schemas, ADRs 22–23 | orchestrator | ✅ `91e9bdb` |
| 0 | Skeleton: deps, containers, DB roles, Alembic, app factory, test harness | orchestrator | ✅ `5f7ecb9` |
| 1 | Core vocabulary: money, clock, watermark, errors, pagination, uow, repository | 2 parallel | ✅ `6d339af` |
| 2 | Ops spine + security + auth | 2 parallel | ⬜ pending |
| 3 | S1 ledger | 1, serial | ⬜ pending |
| 4 | S2 identity/funding · S3 orders · S4 valuation | 3 parallel | ⬜ pending |
| 5 | Independent QA against acceptance criteria | qa-tester | ⬜ pending |
| 6 | Review, CI, docs | mixed | ⬜ pending |

### Wave −1 — close the spec gaps first

Four tables the code cannot compile without had no schema. Each was added to the spec that already
owns its domain rather than invented in code:

| Table | Added to | Why it was needed |
| --- | --- | --- |
| `security` | S4 §3.3 | FK target for `account.security_id`, `order.security_id`, `daily_close.security_id` |
| `market_calendar_cache` | S4 §3.4 | Named only in S0 §3's package layout |
| `sub_period_return` | S4 §3.5 | Named in S4 §5's prose; ADR 3's re-linking property depends on it being stored |
| `customer_cash_lock` | S1 §3.5 | S0 §10.1 requires a canonical per-customer row to `SELECT … FOR UPDATE`; none existed |

### Wave 0 — skeleton (orchestrator, serial)

Not parallelized: everything downstream imports it. Dependencies via `uv`; `docker-compose.yml` and
`docker/postgres/init.sql`; `Makefile`; Alembic wired to the owner role; `app/config.py`,
`app/extensions.py`, `app/__init__.py`, `wsgi.py`; `app/core/crypto.py`; `tests/conftest.py`;
`.importlinter`, ruff and mypy configuration.

**Three database roles**, because S0 §7.3 makes bypassing RLS a credential boundary rather than
application discipline:

| Role | Used by | `BYPASSRLS` |
| --- | --- | --- |
| `trueup_owner` | Migrations only | no |
| `trueup_app` | The web API | **no — structurally incapable of cross-tenant reads** |
| `trueup_worker` | Jobs and the outbox worker | yes, by design |

### Wave 1 — core vocabulary (2 agents, parallel)

- **A** — `core/money.py` (`Money`/`Units`/`Price` + TypeDecorators + Pydantic integration),
  `core/clock.py` (`MarketClock`).
- **B** — `core/errors.py`, `core/pagination.py`, `core/uow.py`, `core/repository.py`.

`core/watermark.py` was written by the orchestrator **before** dispatch: both agents depend on it,
so leaving it inside either one's slice would have made the wave serial in disguise.

### Wave 2 — ops spine + security + auth (2 agents, disjoint packages)

- **C** — `models/ops/` (`inbound_event`, `job_outbox`, `job_run`, `admin_audit_log`,
  `idempotency_key`), `core/idempotency.py`, `services/intake/EventIntakeService`, the outbox
  worker, the `jobs/` CLI base.
- **D** — `core/security.py` decorators, `models/identity/customer.py` **carrying both
  `kyc_status` and `account_approval_status`**, Argon2id auth with TOTP,
  `controllers/api/auth.py`, Talisman/CSRF/Limiter/Redis-session wiring, RLS policies.

Creating `customer` with both status columns here is precisely what lets Wave 4's S3 agent read the
funding gates without depending on the S2 agent's services.

### Wave 3 — S1 ledger (1 agent, serial)

Deliberately not parallelized: the highest-correctness-risk piece, and everything after depends on
it being right. `models/ledger/`, the `DEFERRABLE INITIALLY DEFERRED` zero-sum trigger (ADR 17),
revoked grants, RLS, `PostingService`, `CashPolicyService`, and S1 §7's five invariant tests
including the commit-time trigger test.

### Wave 4 — S2 / S3 / S4 (3 agents, parallel, disjoint)

- **F (S2)** — `kyc_session`, `bank_link`, the KYC/approval/bank-link/deposit/withdrawal services,
  Stripe Identity and Plaid adapters plus fakes, webhook routes.
- **G (S3)** — `order`, `order_event`, `approval_hold`, the state machine, deterministic
  `client_order_id`, hold release on every terminal non-filled path (FR-38), the Alpaca broker
  adapter and the `trade_updates` websocket consumer.
- **H (S4)** — `security`, `market_calendar_cache`, `daily_close`, `valuation_run`,
  `sub_period_return`, `ValuationService`, `TwrService`, `DailyValuationJob`.

### Wave 5 — independent QA (qa-tester)

Verifies against each spec's Acceptance and Edge-case sections; never re-runs or rewrites the
implementer's own tests. RLS isolation in *both* directions, webhook replay idempotency, TWR
unaffected by flow timing (FR-17), `projection == fold(order_event)`, bounced-deposit-after-invest,
`requires_reauth` refusal, and 429 + `Retry-After` on throttled routes. Reports defects; the owning
backend-engineer fixes them.

### Wave 6 — review, CI, docs

Three code-reviewer agents (simplicity/DRY, correctness, conventions); `.github/workflows/ci.yml`
running the gate below plus `pip-audit` and a Trivy image scan; README integration labels;
`CHANGELOG.md`.

## 3. The gate

Every command must pass at every wave boundary. **No wave starts until the previous one is green.**

```sh
docker compose up -d
uv run alembic upgrade head && uv run alembic downgrade base && uv run alembic upgrade head
uv run pytest -q            # unit + integration + api + contract, real PostgreSQL
uv run mypy --strict app
uv run ruff check app tests
uv run lint-imports          # S0 §3's dependency rule, 5 contracts
```

Each wave's commit also updates **`CHANGELOG.md` and [`DECISION-LOG.md`](../../DECISION-LOG.md) in
the same commit** — a decision log assembled retrospectively is worth nothing (non-negotiable #7).

## 4. Seams the orchestrator owns

Never delegated, because parallel agents would collide on them:

- `app/integrations/ports.py` — all six `Protocol`s, written before Wave 4.
- Blueprint registration in `app/__init__.py` — wired at each wave boundary.
- The Alembic revision chain — agents write migration bodies; the orchestrator sets every
  `down_revision` and runs the round-trip. Parallel autogeneration otherwise produces multiple heads.
- Everything under `docs/` — the agent profiles forbid agents from editing it.

## 5. Implementation traps already solved

Worked out before dispatch rather than discovered mid-build:

1. **A deferred constraint trigger never fires under rollback-per-test.** S1 §7's headline test
   asserts the zero-sum trigger rejects an unbalanced entry *at COMMIT* — but a savepoint-rollback
   fixture never commits, so the trigger would silently never run and the test would pass
   vacuously. `tests/conftest.py` exposes `db_session` (rolled back) **and** `db_committing`
   (really commits, truncates after).
2. **RLS does not apply to a table's owner.** An isolation test connected as `trueup_owner` proves
   nothing. `conftest.py` exposes a per-role engine; S0 §7.3's two required tests run as
   `trueup_app`.
3. **`LISTEN`/`NOTIFY` needs a connection outside the pool.** The outbox worker holds its own raw
   `psycopg` connection and drains with `SELECT … FOR UPDATE SKIP LOCKED`, as a separate process.

## 6. End-to-end proof for the S0–S4 slice

register → login → KYC approved via the fake `KycPort` → account approval auto-fires (ADR 21) →
link a bank via fake Plaid → deposit posts a balanced journal entry plus a pending obligation →
place an order below the approval threshold → **replay the same fill event twice and assert exactly
one `order_event` and one ledger entry** → run `DailyValuationJob` →
`GET /api/v1/valuation/balance` returns a value carrying its `completeness` flag.

## 7. Out of scope

- S5–S12 (tax lots, restatement, reconciliation, surfaces, rebalancing, fees, NL assistant,
  production operations).
- The frontend entirely (S8).
- The MCP agent surface (non-negotiable #5) — no S0–S4 spec owns it; tracked as owed work in
  [`DECISION-LOG.md`](../../DECISION-LOG.md).
