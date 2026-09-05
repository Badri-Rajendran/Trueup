# Changelog

## Unreleased

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
