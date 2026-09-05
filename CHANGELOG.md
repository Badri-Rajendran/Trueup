# Changelog

## Unreleased

- Add the S0 core vocabulary (Wave 1): `Money`/`Units`/`Price` value objects with SQLAlchemy and
  Pydantic integration, `Watermark`, `MarketClock`, the `AppError` hierarchy, cursor pagination,
  `UnitOfWork`, and `BaseRepository`. 209 tests.
- `Money`/`Units`/`Price` make dimension errors static, not just runtime: `Money + Units`,
  `Money * Money` and `Money == Units` are `mypy --strict` errors as well as `TypeError`s, and a
  `float` cannot construct or scale any of them. `allocate()` splits pro-rata by largest remainder
  so the leftover penny lands deterministically (non-negotiable #6).
- Add `Money / Units -> Price` and amend S0 §4 and ADR 16 to name two legal cross-dimension
  operations rather than one. S3 §3.1's `average_fill_price` has no other way to be computed
  without unwrapping to a bare `Decimal`, reopening the hole ADR 16 closes. `Money / Price ->
  Units` stays deliberately absent.
- Fix a layering hole: `app/core/uow.py` imported `app/extensions.py`, which S0 §3 forbids
  ("core imports nothing else under `app/`") but the `import-linter` contract did not catch,
  because it listed only the six layers. Contract tightened to include `app.extensions` and
  `app.config`; `DbRole` moved to the new `app/core/db.py` and the session factory is now
  registered at startup, the same inversion `core/crypto.py` uses for the cipher.
- `UnitOfWork` takes its tenant context explicitly instead of reading `flask.g`, so jobs and the
  outbox worker — which have no request context — use the identical transaction boundary, and it
  sets `app.role`/`app.customer_id` per transaction for S0 §7.3's RLS policies.
- Wire `AppError` into the app factory: stable machine-readable `code` reaches the client, while
  the `detail` carried for the audit log never does — an error naming the customer IDs involved
  must not echo them back and confirm a probed identifier exists (OWASP API1).
- Stand up the backend skeleton (S0 Wave 0): dependencies, `docker-compose.yml` (PostgreSQL 16 on
  5433, Redis 7 on 6380 — non-default ports so Trueup cannot collide with another project's
  database), the three database roles S0 §7.3 requires, Alembic wired to the owner role, the Flask
  app factory with Talisman headers/RFC 9457 errors/correlation IDs, health probes, `Cipher` port +
  `EncryptedText` column + both cipher adapters, a `Makefile`, and the four-layer pytest harness.
- Test harness carries two session fixtures on purpose: `db_session` rolls back per test, and
  `db_committing` really commits. S1's `DEFERRABLE INITIALLY DEFERRED` ledger-balance trigger only
  fires at COMMIT, so under a rollback-only fixture the test asserting it rejects an unbalanced
  entry would pass while proving nothing.
- Treat a blank environment variable as unset, not as a value. `.env.example` ships every optional
  credential as `KEY=`, which previously read as "Key Vault is configured" and made startup dial a
  vault at `""` — and would have read a blank `ALPACA_API_KEY_ID` as a real credential.
- Enforce S0 §3's layering with five `import-linter` contracts (`controllers → services → models →
  core`, core importing nothing under `app/`, services reaching providers only through `Protocol`s,
  models importing no services, views never importing an entity).
- Write `README.md`: setup, the three database roles, and an honest live-vs-simulated integration
  table per `real-vs-simulated-rules.md`.
- Close four schema gaps found while planning the S0–S4 build: add `customer_cash_lock` (S1 §3.5,
  the row S0 §10.1 requires for `FOR UPDATE` cash serialization) and `security`,
  `market_calendar_cache`, `sub_period_return` (S4 §3.3–3.5) — all four were referenced by FK or by
  prose but never given a schema.
- Add ADR 22: Alpaca fills arrive over a `trade_updates` websocket, not an HTTP webhook — the Paper
  Trading API (ADR 21) has no webhook events, so S3's `webhooks/alpaca_fills.py` could never have
  worked. Intake, dedupe key, and outbox hand-off are unchanged; only the transport differs.
- Add ADR 23: Azure Key Vault envelope encryption for `bank_link.plaid_access_token` and adviser
  TOTP secrets, with an in-process DEK cache to bound read latency and a local adapter behind the
  same port for dev/CI. Add the matching `.env.example` variables, plus the three separate database
  credentials S0 §7.3 requires.
- Add `.claude/agents/backend-engineer.md` and `qa-tester.md`: senior backend-implementation and
  independent full-stack QA subagent profiles (Sonnet 5, high effort).
- Add ADR 21: Alpaca Paper Trading API (not Broker API) — simulates FR-39's account-approval
  lifecycle, qualifies NFR-12 accordingly. Add `docs/project-helpers/service-accounts.md` (every
  external account/credential the backend needs) and rewrite `.env.example` to match, replacing its
  stale SQLite default.
- Add S12 (production operations, NFR-17–18) and ADR 20: indexing strategy, Azure Application
  Insights alerting, job batching/sharding, SSE + Redis Pub/Sub real-time push, caching, and load
  SLOs — closing six production/real-time efficiency gaps found in a review of S0–S11.
- Write full design specs for S2–S10 (schema, services/engine detail, endpoints, tests), closing the
  gap where only S1 had one. Resolves each spec's deferred parameters (S9's drift band, S3's approval
  threshold, S2's limits, S7's custodian file format); `FEE_RATE_PCT` (S10) is left as a required
  setting with no default, a business decision, not invented here.
- Add S11 (natural-language query assistant, FR-49–54/NFR-15–16): a customer chat interface backed
  by an OpenAI Agent SDK text-to-SQL agent, scoped to curated read-only views, RLS, a least-privilege
  DB role, and a query validator (ADRs 18–19).
- Review the backend foundation design: add ADR 17 (a DB trigger for the ledger's zero-sum invariant,
  and a role-aware RLS policy so adviser/admin cross-customer reads work), split hot-path outbox
  draining onto an always-on worker instead of cron (ADR 13), and fix five smaller consistency gaps
  (idempotency store, cash-lock scope, job cadence, and others) found in `docs/specs/0-backend-
  foundation-design.md` and S1's spec.
- Add the backend foundation design spec and ADRs 13–16: layering (services/integrations/core),
  Azure-scheduled jobs over Celery, session auth with adviser MFA and RLS tenant isolation, and
  typed Money/Units/Price value objects. Update `backend/CLAUDE.md`, `architecture.md`, and
  `requirements.md` to match.
- Gap review: add FR-37–48, NFR-13–14, and ADRs 9–12, closing 13 gaps found in a full doc re-read
  (wash sales, order-hold release, market holidays/timezone, and others). Add S10 (performance fees,
  promoted from stretch scope). Scope Stripe to KYC + fee billing only — rejected as a Plaid
  replacement since Alpaca requires Plaid-linked ACH for funding.
- Add `requirements.md` and link it from `CLAUDE.md`; add a no-Claude-attribution policy bullet
  (session-overridable) to `CLAUDE.md`.
- Initial docs: add `requirements.md`, populate `architecture.md`, and record ADRs 1–8 (ledger,
  settlement, returns, tax lots, cash policy, restatement, orders, rebalancing). Add the S1 (ledger
  core) design spec.
- Rename ADR files `000N` → `N` and update all cross-references.
- Move design specs from `docs/superpowers/specs/` to `docs/specs/` to match the repo's doc
  convention; add it to `CLAUDE.md`'s source-of-truth list.
- Name the project Trueup in `CLAUDE.md`, add an "About Trueup" summary linking the brief, and fix
  the stale "insurance data" rule to "brokerage, or bank data."
- Restructure `CLAUDE.md` into Stack/Ways of working/PRs/CI-CD/Security/Testing/Documentation
  sections; declare the app production-grade and pin the stack.
- Replace the stub `backend/CLAUDE.md` with MVC layering, `uv` tooling, Pydantic, and DRY/SOLID/KISS
  rules.
- Rewrite `frontend/CLAUDE.md` with feature-based React folder structure and hook/state discipline.
- Align `docs/architecture.md` and `backend/CLAUDE.md` on the same controller/view/model mapping.
- Remove `CONTRIBUTING.md` (stale, contradicted `backend/CLAUDE.md`); fold its one rule into root
  `CLAUDE.md`.
- Add a Commands section to `backend/CLAUDE.md` and a Testing section to `frontend/CLAUDE.md` for
  standards that had no corresponding command.
- Add the missing SQLAlchemy stack row, pin Vitest, and remove a duplicate branch rule in
  `CLAUDE.md`.
- Add `docs/requirements/project-description.md` with the product brief.
