# Trueup — Architecture

Source of truth for how the system fits together. Requirements live in
[`docs/requirements/requirements.md`](requirements/requirements.md); the reasoning behind each
structural choice below lives in its ADR under [`docs/decisions/`](decisions/). The backend's
package layering, persistence, jobs, and security mechanics are specified in
[`docs/specs/0-backend-foundation-design.md`](specs/0-backend-foundation-design.md).

## Core principle

> **Append-only truth → derived projection → assert the two agree.**

Storage holds only what happened. Everything else — balances, order status, available cash, the
published return — is computed on read from that history. Where a fast-path projection is kept for
query performance, an equality assertion against the derivation from raw events turns silent data
corruption into a detectable, alertable bug rather than a wrong number nobody notices.

This principle is not a style preference: it is the direct consequence of NFR-1 (never rewrite
history) and NFR-4 (as-published and as-corrected both queryable forever). It shows up three times
independently — the ledger (ADR 1), published-return snapshots (ADR 6), and order state
(ADR 7) — which is why it is named once here instead of re-derived per component.

## Layered pipeline

```
inbound events                  economic truth              lifecycle             derived views
─────────────────               ───────────────              ─────────             ─────────────
broker fill webhooks     ┐
settlement confirmations ┤
deposit/withdrawal events┤
dividend / split events  ┤──▶ idempotent event   ──▶  bitemporal double-  ──▶  obligation &     ──▶  policy functions
custodian file rows      │      intake (dedupe on      entry ledger            order state          (available cash,
daily closing prices     │      execution/fill id,     (postings)             machines             withdrawable,
KYC/Identity verdicts    ┘      or event-specific key)                                              approval threshold)
                                                                                                            │
                                                                                                            ▼
                                                                                              reporting (balances, TWR
                                                                                              returns, tax lots,
                                                                                              statements, reconciliation)
```

- **Event intake.** Every external signal — broker fills, settlement confirmations, deposit
  returns, dividends, splits, price corrections, custodian file rows, **daily closing prices**
  (FR-14, FR-15, NFR-6), and **KYC/Identity verification verdicts** (FR-1–3, FR-39) — enters through
  one idempotent intake path, deduped on an event-specific key (the broker's execution/fill ID for
  fills — never the order ID, since a partial fill produces many fills per order; a provider-issued
  event ID for everything else, e.g. a Stripe Identity `verification_session` ID or a market-data
  vendor's per-close event ID). One component satisfies NFR-5 for every event source rather than one
  polling/dedupe implementation per handler. See ADR 7. **Scheduled jobs** (daily valuation, morning
  reconciliation, monthly rebalance, daily fee accrual) are the other inbound trigger alongside
  webhooks — run by Azure Container Apps Jobs against a Postgres outbox rather than a message
  broker, per ADR 13.
- **Ledger (economic truth).** A bitemporal, append-only double-entry ledger. Every posting carries
  `effective_date` (when it happened) and `recorded_at` (when the system learned it); corrections
  are new postings chained via `superseded_by`, never an `UPDATE`. Units (six decimal places) and
  money are distinct columns that are never arithmetically mixed; a posting's money legs sum to
  zero. See ADR 1.
- **Obligation & order state machines.** Settlement transitions only on custodian confirmation, not
  on a calendar date — `settlement_date` is an expected date used for scheduling and risk, never
  the trigger. Order lifecycle is likewise an append-only event stream with a rebuildable
  projection. See ADR 2, ADR 7.
- **Policy functions.** Available cash is not a stored balance — it is computed. Two distinct
  policies read the same ledger and obligation state: `withdrawable` (settled cash only, the
  brief's one hard constraint) and `investable` (also counts unsettled sale proceeds, so a monthly
  rebalance can sell and buy same-day without a standing cash drag). See ADR 5.
- **Reporting.** Daily valuation, time-weighted returns, tax lots and realized/unrealized gains,
  statements, and morning reconciliation against the custodian file are all read-side derivations
  over the ledger and obligation state — none of them are sources of truth in their own right.

## Sub-project map

Component boundaries follow the sub-project decomposition in the requirements doc. Each gets its
own design spec under `docs/specs/` before implementation.

| Sub-project | Owns | Reads from |
| --- | --- | --- |
| S1 — Ledger & units core | `account`, `journal_entry`, `posting`; balance/available-cash policy functions | event intake |
| S2 — Identity & funding rails | KYC state, bank linking, deposit/withdrawal obligations | S1 |
| S3 — Orders & custody | Order event stream + projection, approval holds | S1 |
| S4 — Valuation & returns | Daily valuation, TWR computation | S1 |
| S5 — Tax lots & corporate actions | Lot lifecycle, FIFO/specific-ID consumption, dividends, splits | S1, S4 |
| S6 — Restatement engine | As-published snapshot + derivation cross-check | S4, S5 |
| S7 — Reconciliation & custodian simulator | Custodian file ingestion, break detection & aging, missed-event backstop | S1 |
| S8 — Surfaces | Customer app, adviser console, statements | all of the above, progressively |
| S9 — Rebalancing | Drift evaluation, order generation, model portfolio target-weight data | S3, S4 |
| S10 — Performance fees | Daily fee accrual, high-water-mark, monthly Stripe charge, dunning | S1, S4, S6 |

## Explicit non-goals

- No internal physical movement of money between "settled" and "in-flight" accounts — settlement is
  a state transition on an obligation, not a ledger posting (ADR 2).
- No second reconciliation loop inside order/event intake — a missed custodian event is
  reconciliation's job (S7), not intake's; duplicating it would create two independently-failing
  sources of truth (ADR 7).
- No mutation of published figures — a correction is always a new, superseding record (ADR 1,
  ADR 6).
