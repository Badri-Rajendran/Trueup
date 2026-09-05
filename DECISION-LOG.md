# Decision Log

Timestamped record of what was decided, what was assumed when no answer was available, and what was
deliberately cut. Written as the work happens, not assembled afterwards — each entry names the
commit that carried it, and `git log` corroborates every date below.

**Distinct from [`docs/decisions/`](docs/decisions/)**, which holds the ADRs. An ADR answers *why
the architecture is shaped this way* and is a permanent design record. This log answers *what was
decided, assumed, or cut, and when* — including the many choices too small for an ADR, and the ones
that are not architecture at all. Entries reference ADRs where one exists; the ADRs carry no date
field of their own, so the date lives here.

Newest first. Times are local (America/Los_Angeles).

---

## Decisions

### 2026-09-05 — Delegation skills for codex and agy

- Added `.claude/skills/delegating-to-codex/` and `.claude/skills/delegating-to-agy/`, so either
  CLI can take a Trueup implementation slice as a co-equal implementer alongside the in-session
  `backend-engineer`, never via git.
- **`agy --print` cannot use any tool non-interactively — not even reading a file — without allow-
  rules in `~/.gemini/antigravity-cli/settings.json`** (not `~/.gemini/settings.json`, a different
  file with the same-looking name). Rules match by **literal string prefix only**: `read_file(/path/)`
  and `write_file(/path/)` work; `read_file(/path/**)` and `read_file(/path/*)` silently fail to
  match. Found empirically after five failed variants; the working form has no glob characters at
  all. `gemini-3.1-pro` alone is also not a valid model name — only `-high`/`-low` suffixed forms
  exist in `agy models`.
- **`codex exec -s workspace-write` sandboxes network access.** A verification run confirmed codex
  cannot reach PostgreSQL on `localhost:5433` from inside that sandbox — it correctly reported the
  connection failure rather than claiming a false pass. It can run `mypy --strict`, `ruff check`,
  `lint-imports`, and pure `tests/unit/` tests; it cannot run the DB-backed test layers. The
  orchestrator running the full gate independently is therefore structural for codex, not only
  discipline.
- Both skills tested per `writing-skills`' RED→GREEN cycle: a naive baseline run against a real gap
  (`app/core/db.py` had no test file) surfaced concrete failures — codex never ran `lint-imports`
  and scoped itself to `tests/unit` only; agy produced 9 `mypy --strict` failures (untyped test
  functions), a `StrEnum`-vs-string comparison bug, `unittest.mock.Mock` instead of a real fake,
  and a coverage-padding test with no real assertion. Both skills were written against those
  specific failures, then verified: a second run through the actual skill template passed the full
  gate (213 tests, `mypy --strict` clean, `ruff` clean, `lint-imports` 5/5) for both CLIs, with agy
  self-correcting the exact `StrEnum` bug from its own baseline once the skill's non-negotiables
  named it.

### 2026-09-05 00:12 — S0 core vocabulary (`6d339af`)

- `Money`/`Units`/`Price` make dimension errors **static as well as runtime**: `Money + Units`,
  `Money * Money` and `Money == Units` fail `mypy --strict` in addition to raising `TypeError`, and
  no `float` can construct or scale any of them (ADR 16).
- **Added `Money / Units → Price`, amending S0 §4 and ADR 16 from one legal cross-dimension
  operation to two.** S3 §3.1's `average_fill_price` has no other route that does not unwrap to a
  bare `Decimal` — which is exactly the hole ADR 16 exists to close. The agent implementing money
  flagged this rather than inventing the operator; the spec was amended before the code shipped.
- `allocate()` splits pro-rata by largest remainder, so the leftover penny lands deterministically
  (non-negotiable #6).
- `UnitOfWork` takes tenant context **explicitly** rather than reading `flask.g`, so jobs and the
  outbox worker — which have no request context — share one transaction boundary.
- **Fixed a layering hole the contract had missed.** `app/core/uow.py` imported `app/extensions.py`,
  which S0 §3 forbids ("core imports nothing else under `app/`") but `import-linter` allowed,
  because the contract listed only the six layers. The contract now covers `app.extensions` and
  `app.config`; `DbRole` moved to `app/core/db.py` and the session factory is registered at startup.
  A weak contract that passes is worse than no contract, because it reads as proof.

### 2026-09-04 23:42 — Backend skeleton (`5f7ecb9`)

- **Three database roles, not one** — `trueup_owner`, `trueup_app` (no `BYPASSRLS`),
  `trueup_worker` (`BYPASSRLS`). S0 §7.3 makes tenant isolation a credential boundary; the web
  API's credential is now structurally incapable of a cross-tenant read regardless of any future
  request-handling bug.
- **Two test session fixtures on purpose.** `db_session` rolls back per test; `db_committing`
  really commits. S1's `DEFERRABLE INITIALLY DEFERRED` ledger-balance trigger only fires at COMMIT,
  so under a rollback-only fixture the test asserting it rejects an unbalanced entry would pass
  while proving nothing.
- **PostgreSQL on 5433 and Redis on 6380**, not the defaults — another project on the same machine
  already held 5432. Non-default ports permanently, so Trueup cannot be pointed at or mistaken for
  the wrong database.
- **A blank environment variable now reads as unset, not as a value.** Found by a smoke test:
  `.env.example` ships every optional credential as `KEY=`, and an empty string is not `None`, so
  `AZURE_KEY_VAULT_URL=` read as "Key Vault is configured" and startup tried to dial a vault at
  `""`. The same flaw would have read a blank `ALPACA_API_KEY_ID` as a real credential.
- `.gitignore` no longer excludes `frontend/src`, which would have silently dropped every new
  frontend file from future commits.
- Plain SQLAlchemy 2 rather than Flask-SQLAlchemy: S0 §5 puts the session inside the unit of work,
  and Flask-SQLAlchemy's request-scoped session fights that ownership.

### 2026-09-04 23:28 — Spec gaps closed; ADRs 22–23 (`91e9bdb`)

- **Four tables were referenced by FK or prose but had no schema** — `security`,
  `market_calendar_cache`, `sub_period_return`, `customer_cash_lock`. Each was added to the spec
  that owns its domain **before** any code, rather than invented inside an implementation.
- [ADR 22](docs/decisions/22-alpaca-trade-updates-websocket-intake.md): Alpaca fills arrive over a
  `trade_updates` websocket, not an HTTP webhook. The Paper Trading API chosen in ADR 21 has no
  webhook events at all — only Broker API does — so S3's `webhooks/alpaca_fills.py` could never
  have worked. Intake table, `execution_id` dedupe key and outbox hand-off are unchanged; only the
  transport differs.
- [ADR 23](docs/decisions/23-key-vault-envelope-encryption.md): Key Vault envelope encryption for
  `bank_link.plaid_access_token` and adviser TOTP secrets. Per-record AES-256-GCM data keys wrapped
  by an RSA key that never leaves the vault, with an in-process DEK cache so only cache misses
  cross the network.

### 2026-09-04 22:37 — Alpaca product choice (`08a6f64`)

- [ADR 21](docs/decisions/21-alpaca-paper-trading-not-broker-api.md): **Alpaca Paper Trading API,
  not Broker API.** Broker API requires an application and an open-ended approval wait before any
  sandbox access exists, incompatible with the timeline.
- **Consequence, stated rather than glossed:** FR-39's brokerage-side account-approval lifecycle is
  **simulated**, because this product has no per-customer onboarding verdict to wait on. NFR-12 is
  qualified accordingly in `requirements.md` — order placement, fills, positions and market data
  are genuinely live; only the approval verdict is not.

### 2026-09-04 21:23 — Production operations (`8ec31f9`)

S12 and [ADR 20](docs/decisions/20-observability-and-realtime-push.md): Azure Application Insights
for observability, SSE + Redis Pub/Sub for real-time push — no new vendor, reuses Redis.

### 2026-09-04 21:01 — Specs S2–S11 (`cb5b180`)

- Full design specs written for S2–S10 and S11, closing the gap where only S1 had one.
- Deferred parameters resolved: S9's drift band, S3's approval threshold, S2's limits, S7's
  custodian file format.
- **`FEE_RATE_PCT` deliberately left with no default** — a business decision, not one to invent in
  a spec.
- ADRs 18–19: OpenAI Agent SDK as the LLM vendor, and the read-only SQL tool's safety perimeter.

### 2026-09-04 17:42 — Backend foundation (`e480687`)

ADRs 13–17: Azure Container Apps Jobs over Celery (a broker holding in-flight financial work is a
second source of truth); layered architecture with repository and unit of work; server-side session
auth with mandatory adviser MFA; typed money value objects; a database trigger for the ledger's
zero-sum invariant plus role-aware RLS. Hot-path event draining was split onto an always-on worker
instead of cron, fixing FR-9's processing latency.

### 2026-09-04 14:30 — Requirements and ADR framework (`0acb2f8`)

48 FRs, 14 NFRs, ADRs 1–12. **Stripe scoped to KYC and fee billing only** — rejected as a Plaid
replacement, since Alpaca requires Plaid-linked ACH for funding.

---

## Assumptions

Made because no answer was available. Each names what changes if it turns out wrong.

| Assumption | If wrong |
| --- | --- |
| **No provider credentials yet** → real adapters *and* fakes built now; contract tests parametrize over both and auto-skip the real side until keys land. Nothing inside the application is mocked. | Nothing structural. The real adapters already exist; supplying keys flips the skipped tests on. |
| **`KYC_MAX_ATTEMPTS = 3`; deposit caps $25,000 per transaction, $50,000 per day.** Defensible engineering defaults, **flagged for compliance review against actual NACHA/ACH network limits before go-live** — not a compliance sign-off. | Settings change, no code or schema change. |
| **`ORDER_APPROVAL_THRESHOLD_USD = $10,000`**, with `> threshold` requiring approval and `<= threshold` not. The boundary is stated explicitly so it is not left to whichever comparison operator gets typed first. | Setting change. |
| **`inbound_event.signature_verified = true` for the Alpaca websocket**, on the strength of the authenticated TLS session: Trueup opens the connection to Alpaca's own host with its own key, so there is no per-message signature and no third party who could inject one. This differs from Stripe and Plaid, where an unauthenticated public endpoint makes the signature the only trust anchor. | The column's meaning would need splitting per source. Recorded in ADR 22 so the difference is never silent. |
| **Local `.env` generated for development** with a random `SECRET_KEY` and `LOCAL_CIPHER_KEY`; gitignored, containing only docker-compose credentials. Alembic cannot run without settings. | None — it is developer-local and never committed. |

---

## Cuts and deferrals

Deliberately not built. Each is a choice, not an oversight.

- **S5–S12 and the entire frontend** — outside the current S0–S4 slice.
- **The MCP agent surface (non-negotiable #5)** — **owed work, currently unscoped.** No FR in
  `requirements.md`, no spec, and no ADR covers it. Recorded here so it stops being invisible.
- **`Money / Price → Units`** — the remaining algebraic inverse. Nothing in S0–S12 needs it, and an
  untested operator on a money path is a liability rather than a convenience. Its absence is
  documented in the module so it reads as a decision.
- **Bounced-deposit collection and write-off policy** (S2 §9) — the resulting debt is recorded
  correctly as a `correction` entry against a `customer_receivable` account; recovering it is not
  designed.
- **Re-screening an already-approved customer against a later sanctions hit** —
  `requirements.md`'s own stated out-of-scope item.
- **Polling as a fill-delivery mechanism** — retained only as S7's morning reconciliation backstop,
  which is a reconciliation feature in its own right (non-negotiable #4). Non-negotiable #2 is
  satisfied rather than worked around.
- **Adding `Date:` fields to the 23 existing ADRs** — this log carries the dates instead, avoiding
  23 files of churn for the same traceability.

---

## Known inconsistencies, flagged not fixed

- **S0 §7.4 records "LLM Top 10: not applicable to v1 — no AI/LLM feature is in scope."** S11 and
  ADR 18 later added an OpenAI-backed assistant, so that line is now stale. Outside the S0–S4
  slice; left for a deliberate decision rather than edited in passing.
