# Documentation Review Memory

Date: 2026-09-05  
Scope: Complete `docs/` tree — 45 files, approximately 5,500 lines.  
Method: Parallel review of requirements, architecture, provider/delivery guidance, all ADRs, and S0–S12 specifications.  
Status: Analysis only; no design or code changes were made.

## Executive synthesis

Trueup's documentation presents a regulated retail-investing platform for USD and US-listed
equities/bonds. Its central design is coherent and intentionally defensive:

- The application-owned ledger is immutable, append-only, double-entry, and bitemporal.
- Projections such as orders, valuations, and published statements are derived from durable truth
  and must be independently reproducible.
- Provider facts enter through a common, signature-validated, idempotent intake/outbox path.
- Customer access is enforced at controller, repository, and PostgreSQL Row-Level Security layers.
- Market/return reporting distinguishes live corrected truth from immutable as-published figures.
- The natural-language assistant is constrained by database permissions, curated views, static SQL
  validation, limits, and audits rather than by its prompt.

## Delivery dependency model

```text
S0 foundation -> S1 ledger -> S2 funding / S3 orders -> S4 valuation
                              -> S5 lots -> S6 restatement -> S7 reconciliation
                              -> S9 rebalancing / S10 fees / S11 assistant
                              -> S8 surfaces / S12 production operations
```

The current delivery plan covers S0–S4 only. It must be extended before later functional scope is
treated as planned or release-ready.

## Governing invariants

1. Use typed immutable `Money`, `Units`, and `Price`; never floats. Financial values serialize as
   strings and preserve their dimensions.
2. Every money journal entry balances to zero and must be verified at PostgreSQL commit time.
3. Corrections are new economic facts, never overwritten history. Historical calculations use a
   specific `recorded_at` publication watermark.
4. Settlement is confirmation-driven; an expected T+1 date is not a booking trigger.
5. `withdrawable` cash and `investable` cash are distinct derived policies. Mixing them at an
   endpoint is a regulatory-grade error.
6. TWR excludes deposits and withdrawals from investment performance by construction.
7. Event intake must validate source authenticity, deduplicate durably, tolerate order variance,
   and be replay-safe.
8. Reconciliation breaks are visible, aged, and resolved by a human—never silently auto-corrected.
9. Jobs and external calls follow intent -> outbox -> commit -> call -> retry. Provider I/O does
   not occur inside a database transaction.
10. Redis may support sessions, throttling, and ephemeral SSE fanout, but PostgreSQL remains the
    durable state for financial work in flight.

## Provider and simulation boundaries

- Selected integrations are Alpaca Paper Trading, Plaid Sandbox, Stripe Identity and Billing test
  mode, OpenAI, Azure, and GitHub.
- Alpaca Paper is live sandbox infrastructure, but customer brokerage approval is necessarily
  simulated and must be labelled as such.
- Plaid bank linking is intended to be live sandbox; ACH transfer lifecycle may be simulated when
  Plaid Transfer is unavailable. The acceptance boundary needs to be made explicit.
- The custodian reconciliation file is intentionally simulated in v1 and must be structurally
  labelled as simulated.
- At least two third-party integrations must work end-to-end in a deployed environment; remaining
  simulated substitutes need equivalent interfaces and unambiguous labelling.

## Critical issues to resolve before implementation

| Priority | Finding | Required resolution |
| --- | --- | --- |
| Critical | S1 calls the ledger append-only but describes setting `superseded_by` on an existing journal entry. | Point from the new correction to the prior entry (`supersedes_entry_id`), or use a separate immutable relationship table. Do not mutate the original fact. |
| Critical | PostgreSQL `CHECK` constraints cannot inspect an account row while validating a posting's dimension. | Use a trigger, a composite foreign key, or a safely denormalized constrained dimension. |
| Critical | Foundation RLS examples expect `posting.customer_id`, while the proposed posting schema has only `account_id`. | Define tenant keys and RLS policy/query strategy consistently for postings, entries, obligations, and each customer-owned table. |
| Critical | S2 permits immediate investment of unsettled deposits; S1's investable-cash formula does not include them. | Add explicitly controlled provisional deposits to the formula, or remove the promise of immediate investability. Preserve the post-investment ACH-return debt treatment. |
| High | Several documents say broker fill webhooks, while ADR 22 specifies Alpaca Paper `trade_updates` WebSocket intake and explicitly supersedes the old S3 HTTP-webhook plan. | Update requirements/architecture/helpers to refer to provider event delivery and the Alpaca WebSocket exception. Build only the common stream-to-intake path. |
| High | S5 needs CUSIP, designation override, expected settlement, confirmation, and sale-date data not specified by S3/S4 schemas. | Add those fields or explicit relationships before building tax-lot selection, finality, and wash-sale logic. |
| High | S6 requires watermark-consistent historic valuation; S4's `value_book` does not accept/filter by a watermark. | Make every ledger, price, lot, and position read involved in historic derivation share a concrete `Watermark`. |
| High | `restatement_event.trigger_source_event_id` is described as referring to either an inbound event or a journal entry. | Replace the polymorphic pseudo-FK with explicit nullable FKs plus a constraint, or a causal-event association table. |
| High | The mandatory MCP surface has no accountable design/spec owner. | Define its read tools, approval-queued write flow, tenant/auth model, forbidden autonomy policy, and acceptance tests. |
| High | `daily_close` both models `missing` as a stored status and says missing is inferred from absent rows. | Choose a materialized-missing or derived-absence model and align schema, uniqueness, jobs, and APIs. |

## Material design issues and open parameters

- S10 must base high-water-mark fees on a TWR-adjusted performance index, not raw portfolio value;
  otherwise deposits can be charged as gains. Its edge-case text identifies this correctly but the
  primary pseudocode should be corrected.
- S3's binary approval-hold model lacks remaining-reservation mechanics for partial fills followed
  by cancellation/rejection. `open_buy_commitments` needs a concrete contract.
- S5 mutates lots/adjusted basis for splits and wash sales but lacks a bitemporal/audit versioning
  model; this may prevent reliable historical tax/statement derivation at a publication watermark.
- A single fill can cause several domain facts. `journal_entry.source_event_id` and
  `settlement_obligation.source_event_id` uniqueness need clear causal/idempotency cardinality.
- TWR subperiod boundaries, flow inclusion, and the effect of a corrected close inside a subperiod
  need precise semantics before relying on local/O(1) restatement claims.
- Statement retrieval needs an identifier/selection rule if multiple snapshots exist for a period.
- S9 should explicitly branch for zero target weight rather than using relative drift division;
  zero target plus nonzero holding should produce a full-exit sell.
- S8's blanket ownership claim cannot apply literally to anonymous auth routes. State endpoint-level
  auth requirements precisely.
- Exact deterministic rounding/residual allocation is mandatory but unresolved.
- Model holdings/weights, fee rate, fee-payment instrument/consent, client surface (mobile/web),
  adviser-console packaging, tax-export format beyond CSV, and customer-facing bounced-deposit
  handling remain open product decisions.

## Security and operations follow-through

- Adviser/admin sessions require MFA and every privileged action requires an append-only audit row.
- RLS proof tests must demonstrate structural absence of one customer's rows from another
  customer's query result; policy existence alone is insufficient.
- `security_invoker` is mandatory on chat reporting views. The `chat_readonly` role has grants only
  on those views, never raw tables, and each query has AST validation, a 3-second-style timeout,
  and an enforced row cap.
- Before live customer data is sent to OpenAI, confirm the strictest available data-retention and
  privacy setting. This is a release blocker external to code.
- Production operations should add concrete health/disconnect-duration alerting for the always-on
  worker and Alpaca stream. Existing job-run alerts are not sufficient for these services.
- Define Alpaca calendar cache/outage behavior at daily boundaries, Key Vault rotation cadence and
  outage runbook, alert routing, load-test target customer count, and final SLO thresholds.
- Every foreign key and documented query path needs the explicit index strategy defined in S12;
  verify use with integration-level `EXPLAIN ANALYZE` assertions.

## Requirements traceability and documentation maintenance

- Requirements-to-S1–S12 ownership matrices omit expanded/new FR assignments, including FR-37–44
  and parts of FR-45–54/NFR-17–18. Update ownership before implementation planning.
- `architecture.md` should include S12 and should be aligned with ADR 22's WebSocket intake.
- The generic provider menu is non-binding and contains a leftover reference to “Corgi”; correct it
  if retained.
- The written six-week target conflicts with later-added fees and NL assistant scope, and with a
  delivery plan stopping at S4. Produce a sequenced plan through S12, including the MCP surface.

## Primary sources

- `docs/requirements/` — product, functional/nonfunctional requirements, and non-negotiables.
- `docs/architecture.md` — cross-cutting architecture and data-flow overview.
- `docs/decisions/` — 23 accepted ADRs; later ADRs supersede earlier conflicting direction.
- `docs/specs/00-backend-foundation-design.md` through `12-production-operations.md` — implementation
  contracts and acceptance/test strategy.
- `docs/delivery/backend-build-plan-phase-1.md` — current S0–S4 delivery sequencing.

