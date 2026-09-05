# S10 — Performance Fees: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-45–48
Depends on: S1 (ledger — fee postings are ordinary journal entries on new account roles), S4 (TWR
figures, the fee basis), S6 (the publish watermark the fee-lock rule depends on)
Consumed by: S8 (a customer-facing fee/payment-method screen), S11's own spec already reads S1's
`fees_accrued_payable` etc. only indirectly via its curated views — no direct dependency here

ADR 10 already decided the full mechanism (TWR-gain-above-high-water-mark, dual ledger events,
Stripe-only charge path, as-published lock). This spec is where that mechanism becomes concrete
schema and services. **The fee rate itself is a required setting with no default
(`FEE_RATE_PCT`)** — a deliberate business decision left for deploy time, not invented in this spec
(see this sub-project's own plan discussion); everything else below is fully specified.

## 1. Purpose

Accrue a performance fee daily from TWR-derived gain against a per-customer high-water-mark, never
charging twice for the same gain across a drawdown-then-recovery cycle (FR-45); charge the accrued
amount monthly via the customer's Stripe-linked payment method, never touching Alpaca cash (FR-46);
lock the fee basis to the as-published figure at charge time, with a later restatement never
reopening an already-charged fee (FR-47); and handle a failed charge with a defined, visible
retry/dunning state (FR-48).

## 2. Non-goals

- The fee rate's actual value — a deploy-time setting, not this spec's to state.
- Refunding/reclaiming an already-charged fee after a restatement — explicitly out of v1 scope per
  ADR 10's own alternatives-considered section; this spec implements the disclosed-limitation
  approach, not a reclaim mechanism.

## 3. Schema

### 3.1 New S1 account roles (S1 §3.1's enum, extended per that spec's own stated extensibility)

`fees_accrued_payable` (customer-scoped liability), `fee_revenue_accrued` (house),
`fee_revenue_collected` (house) — all `dimension = money`, no schema change to `account` itself
beyond adding these three role values.

### 3.2 `high_water_mark`

| Column | Type | Notes |
| --- | --- | --- |
| `customer_id` | uuid, FK, unique | one row per customer, updated in place — this is the **one**
  intentional exception to the append-only posture elsewhere in this design: a high-water-mark is a
  derived summary value, not a source-of-truth economic fact; the economic facts (each day's TWR
  gain, each charge) remain fully append-only in the ledger, and the HWM is always re-derivable from
  them if this row were ever lost — it is a cache, not a ledger. |
| `peak_value` | `Money` | the highest cumulative value on which a fee has already been charged |
| `updated_at` | timestamptz | |

### 3.3 `fee_accrual`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `accrual_date` | date | one row per customer per day (`UNIQUE (customer_id, accrual_date)`) |
| `gain_amount` | `Money` | the day's TWR-derived dollar gain above the high-water-mark (zero if the customer is still below their peak) |
| `fee_amount` | `Money` | = `gain_amount × FEE_RATE_PCT`, using Actual/365 day-count (see §5) |
| `journal_entry_id` | uuid, FK | the `fee_accrual` posting (ADR 10) this row corresponds to |

### 3.4 `fee_charge`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `billing_period_start`, `billing_period_end` | date | a calendar month, per ADR 10's monthly cadence |
| `total_accrued` | `Money` | sum of `fee_accrual.fee_amount` over the period |
| `as_published_watermark` | timestamptz | **the S6 publish watermark this charge is locked to** (FR-47) — set once at charge time, never updated |
| `status` | enum | `pending` \| `succeeded` \| `failed` \| `dunning` |
| `stripe_charge_id` | text, unique, nullable | set on a successful Stripe charge — the dedupe key for Stripe webhook events (foundation spec §6's pattern) |
| `journal_entry_id` | uuid, FK, nullable | the `fee_charge` posting (ADR 10), set only once `status = succeeded` |

### 3.5 `dunning_state`

| Column | Type | Notes |
| --- | --- | --- |
| `fee_charge_id` | uuid, FK, unique | |
| `attempt_number` | int | |
| `next_retry_at` | timestamptz | |
| `max_attempts` | int | default `DUNNING_MAX_ATTEMPTS = 4` — a tunable setting |
| `status` | enum | `retrying` \| `exhausted` — `exhausted` means all attempts failed and the failure is now a
  standing, customer-visible balance owed, not a silently-abandoned charge (FR-48's "never silently
  dropped") |

## 4. `FeeAccrualService` and `HighWaterMarkService`

```
DailyFeeAccrualJob.run(accrual_date):
    for each customer with an active model assignment:
        current_value = S4.value_book(customer_id, accrual_date).total_value
        hwm = HighWaterMarkService.get(customer_id)   # creates at first-ever value if absent
        gain_above_hwm = max(0, current_value - hwm.peak_value)
        # a drawdown-then-recovery accrues NOTHING until current_value exceeds the prior peak —
        # this max(0, ...) is the entire high-water-mark guarantee (FR-45), not a separate check
        fee = gain_above_hwm * FEE_RATE_PCT * (1/365)   # Actual/365 daily accrual, ADR 10 defended below
        post fee_accrual entry: debit fees_accrued_payable, credit fee_revenue_accrued  (S1 posting,
             money sum to zero: fee debited on one side, credited on the other — no new ledger
             mechanism, per ADR 10)
        insert fee_accrual row (§3.3)
        if current_value > hwm.peak_value: HighWaterMarkService.update(customer_id, current_value)
             # the peak only ratchets UP, on the value that actually generated this accrual —
             # updated in the SAME transaction as the accrual posting, so the two can never
             # diverge (a partial failure rolls back both together)
```

**Actual/365 day-count, defended**: the standard US retail daily-accrual convention (consistent with
NFR-9's US-market scope) — chosen over Actual/360 (a money-market/banking convention with no
particular relevance to a retail investment product) or a 30/360 convention (designed for fixed
coupon schedules, not a continuously-accruing daily fee). This is the one sub-decision this spec
makes and defends itself, distinct from the fee rate, which it deliberately does not.

## 5. `FeeChargeService` and `DunningService`

```
MonthlyFeeChargeJob.run(billing_period):
    for each customer with fee_accrual rows in billing_period:
        total = sum(fee_amount for those rows)
        watermark = S6.SnapshotService.publish(customer_id, billing_period).publish_watermark
             # FR-47: publication happens (or is confirmed already done) BEFORE the charge locks to
             # it — a charge is never locked to a watermark that doesn't correspond to an actual
             # publication event, mirroring S6 §7's own rule against arbitrary caller-supplied
             # timestamps
        insert fee_charge(status='pending', as_published_watermark=watermark, total_accrued=total)
        persist intent + job_outbox row, commit   (foundation spec §5's no-I/O-in-transaction rule —
             this is a provider call, treated identically to any other)
        -- outbox worker calls Stripe --
        on Stripe success:
            fee_charge.status = 'succeeded', stripe_charge_id = <id>
            post fee_charge entry: debit fee_revenue_accrued, credit fee_revenue_collected;
                 clear fees_accrued_payable for the charged amount   (ADR 10's dual-event design)
        on Stripe failure:
            fee_charge.status = 'failed'
            DunningService.start(fee_charge_id)   -- never reverses the accrual (ADR 10: "a failed
                 charge does not reverse the accrual — the liability remains posted and owed")

DunningService.retry(fee_charge_id):
    attempt Stripe charge again
    on success: fee_charge.status = 'succeeded' (same posting as above), dunning_state deleted/closed
    on failure:
        dunning_state.attempt_number += 1
        if attempt_number >= max_attempts: dunning_state.status = 'exhausted', fee_charge.status = 'dunning'
             -- FR-48: 'dunning'/'exhausted' is a customer-visible state (S8), never a silent drop;
                the liability (fees_accrued_payable) remains posted and owed indefinitely, matching
                the bounced-deposit debt treatment in S2 §5.2 — both are "a real amount owed that
                this spec doesn't build a collections flow for," stated consistently rather than
                two different half-solutions
        else: dunning_state.next_retry_at = now() + backoff(attempt_number)
```

`DunningRetryJob` runs under the foundation spec's `continuous` cadence (§9 of that spec) — it
legitimately fires multiple times as retries come due, not once a day.

## 6. Restatement interaction (FR-47, the property this spec must not violate)

A restatement (S6) landing for a period that already has a `succeeded` `fee_charge` does **not**
reopen that charge — `fee_charge.as_published_watermark` is immutable once set, and
`FeeChargeService` never re-derives a past charge's amount from the live figure. The only required
behavior this spec adds: when `RestatementService` (S6 §4) processes a correction, it checks whether
any `fee_charge` for the affected period has `status = succeeded`, and if so, flags the customer
account for a **disclosure** (a new `fee_restatement_disclosure` row: `customer_id, fee_charge_id,
restatement_event_id, created_at`) — surfaced to the customer via S8, per ADR 10's explicit "disclosed
as a documented limitation" resolution rather than a silent mismatch nobody is told about.

## 7. API contract

- `GET /api/v1/fees` → accrual-to-date, high-water-mark, charge history, current `dunning`/`exhausted`
  state if any.
- `POST /api/v1/payment-methods` → attach/update the customer's Stripe-linked payment method
  (Stripe Elements client-side tokenization; Trueup never handles raw card data — PCI scope stays
  with Stripe, consistent with root `CLAUDE.md`'s general "buy don't build" posture for anything
  payment-adjacent).
- `webhooks/stripe_billing.py` → through the shared intake path, keyed on Stripe's charge/event ID
  (ADR 10).

## 8. Edge and corner cases

1. **A customer's value is below their all-time high-water-mark for an extended period** — zero
   accrual every day during that stretch; the first day it exceeds the *prior* peak, accrual resumes
   only on the amount above that peak, never retroactively "catching up" on the drawdown period.
2. **A customer deposits new cash, which mechanically raises their value above the prior peak with
   no investment gain at all** — `HighWaterMarkService` would incorrectly treat this as chargeable
   gain unless deposits are excluded; **resolution**: `gain_above_hwm` must be computed from the
   **TWR-derived gain** (ADR 10 §"Basis" — reuses S4's TWR, which structurally excludes flows by
   construction, FR-17) applied to the peak, not from raw portfolio value directly — §4's pseudocode
   above is written in terms of `current_value` for readability, but the actual `HighWaterMarkService`
   implementation must track the peak in TWR-adjusted terms (a "TWR-index" value that only moves with
   investment performance) precisely so a deposit alone can never trigger a fee. Stated explicitly
   here because it is the single most consequential correctness requirement in this entire
   sub-project — getting it wrong charges a fee on the customer's own money, not a gain.
3. **A charge succeeds, then a chargeback/dispute arrives from Stripe later** — treated as a new
   Stripe event through the same webhook path; `fee_charge.status` gains no new `disputed` value in
   v1 (out of scope, consistent with NFR-11's timeline) — noted as an open parameter, not silently
   unhandled.
4. **`DailyFeeAccrualJob` runs twice for the same day** (a retry after a partial failure) — the
   `UNIQUE (customer_id, accrual_date)` constraint on `fee_accrual` makes the second attempt's insert
   fail cleanly rather than double-accrue; the job is written to treat that unique violation as
   "already done for today," per the foundation spec's general job-idempotency requirement.
5. **A customer closes their account with `fees_accrued_payable` still owed** (never charged, or
   charge exhausted) — the debt remains on the books; a final-charge/write-off flow at account
   closure is explicitly out of scope, same treatment as edge case 3 above.

## 9. Testing strategy

- **Unit** — the high-water-mark ratchet-only-up property; the deposit-vs-gain distinction (edge case
  2) as a dedicated property test: a pure deposit with zero market movement must accrue exactly zero
  fee, over many randomized deposit/gain combinations; the dunning backoff/exhaustion sequencing.
- **Integration** — the accrual-and-HWM-update-in-one-transaction guarantee (kill mid-way, assert
  neither persisted, matching S3's own hold-release transactional test pattern); the
  `as_published_watermark` immutability (attempt an `UPDATE`, assert it's rejected at the DB level,
  consistent with this design's general append-only posture for anything a customer was already
  shown).
- **Contract** — `PaymentPort`'s real (Stripe Billing) and fake adapters against identical
  success/failure/webhook event shapes.

## 10. Open parameters (not blocking this spec)

- **`FEE_RATE_PCT`** — required, no default, a deploy-time business decision (stated once, the
  single most important open item in this spec).
- `DUNNING_MAX_ATTEMPTS` (default 4) and the retry backoff schedule — tunable settings.
- A `disputed` charge state and any chargeback-handling flow — deferred, per edge case 3.
