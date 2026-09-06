# S7 — Reconciliation & Custodian Simulator: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-30–33, FR-44
Depends on: S1 (ledger — the internal side of every reconciliation comparison), ADR 12 (market
calendar — the holiday-vs-break distinction), ADR 7 (the missed-fill backstop this spec owns, per
that ADR's explicit division of responsibility)
Consumed by: S8 (the adviser-facing break screen with aging), S3 (a same-day-unconfirmed fill that
this spec's morning run catches is the backstop ADR 7 deferred here)

This spec closes gap finding #13: `requirements.md` explicitly deferred "custodian file format/schema
and match granularity" to this spec — resolved below, not assumed away.

## 1. Purpose

Every morning, reconcile positions, cash, and transactions against an external custodian file
(FR-30); surface breaks on a screen with an aging indicator, not a log line (FR-31); detect a single
tampered/incorrect position (FR-32, the live-fire test this platform is explicitly graded on);
provide a clearly-labelled simulator able to inject a late dividend and a corrected closing price
(FR-33); and ensure a detected break is resolved only by a human, never auto-corrected (FR-44).

## 2. Non-goals

- Same-day missed-fill detection — this spec's morning cadence is FR-30's own stated cadence
  ("every morning"); a same-day backstop was explicitly evaluated and rejected in ADR 7 as scope
  creep duplicating this sub-project's own machinery.
- What happens to the ledger once a break is manually resolved — FR-44 says the system never
  auto-corrects; the human's resolution action (whatever ledger correction they decide to apply, if
  any) goes through S1's normal `superseded_by` mechanism like any other correction, not a
  bespoke reconciliation-specific write path.

## 3. Custodian file format (closing gap finding #13)

Three files per morning run, one per comparison surface — kept separate rather than one combined
file, since positions/cash/transactions have different natural keys and different match logic:

### 3.1 `positions.csv`

| Column | Notes |
| --- | --- |
| `customer_id`, `security_id` | the match key — one row per (customer, security) the custodian believes is held |
| `quantity` | six decimal places, matching FR-11's own precision |
| `as_of_date` | the custodian's stated as-of date for this file |

### 3.2 `cash.csv`

| Column | Notes |
| --- | --- |
| `customer_id` | the match key — one row per customer |
| `settled_cash` | the custodian's view of settled cash — compared against S1's `settled_cash(customer)` (S1 §5), not `investable`/`withdrawable`, since the custodian has no notion of Trueup's own hold/commitment policy layer |
| `as_of_date` | |

### 3.3 `transactions.csv`

| Column | Notes |
| --- | --- |
| `custodian_transaction_id` | the match key — one row per custodian-side transaction |
| `customer_id`, `security_id` (nullable for cash-only transactions) | |
| `transaction_type` | `trade` \| `dividend` \| `deposit` \| `withdrawal` \| `fee` |
| `amount_money`, `quantity` (nullable) | |
| `effective_date` | |

Each file is ingested into a corresponding `custodian_file_row` table (one row per source row, with
a `file_type` discriminator), preserving the raw import for audit before any comparison logic runs —
consistent with the foundation spec's event-intake principle of persisting the raw fact before
deriving anything from it.

## 4. Match granularity

- **Positions**: matched per `(customer_id, security_id)` — the finest grain that means anything for
  a position; a quantity mismatch of any size at this grain is a break (no materiality threshold in
  v1 — FR-32's live-fire test plants a single-position discrepancy and expects it caught, not
  filtered out by a tolerance band).
- **Cash**: matched per `customer_id` — Trueup's internal `settled_cash(customer)` (S1 §5) compared
  directly against the custodian file's `settled_cash`.
- **Transactions**: matched per `custodian_transaction_id` against Trueup's own `source_event_id`
  linkage (every S1 journal entry that has an external counterpart already carries this, since S1
  §3.2 requires `source_event_id` for exactly this kind of downstream traceability) — a custodian
  transaction with no matching internal entry, or vice versa, is a break.

## 5. Schema

### 5.1 `custodian_file_row`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `file_type` | enum | `positions` \| `cash` \| `transactions` |
| `raw_row` | jsonb | the untouched source row, per §3's preservation principle |
| `import_batch_id` | uuid | groups all rows from one morning's three files together |
| `imported_at` | timestamptz | |

### 5.2 `reconciliation_break`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `break_type` | enum | `position_mismatch` \| `cash_mismatch` \| `unmatched_custodian_transaction` \| `unmatched_internal_transaction` |
| `customer_id` | uuid, FK, nullable | null only for a break with no single-customer attribution (rare; e.g. a malformed file row) |
| `expected` | jsonb | Trueup's internal value |
| `actual` | jsonb | the custodian file's value |
| `opened_at` | timestamptz | |
| `status` | enum | `open` \| `resolved` |
| `resolved_at`, `resolved_by`, `resolution_note` | nullable | **FR-44**: `resolved_by` is always a human `actor_id` — there is no system-generated resolution path; a `resolved` break with no `resolved_by` is itself a bug the tests below assert against |
| `import_batch_id` | uuid, FK | |

No `UPDATE`/`DELETE` on `opened_at`/`expected`/`actual` once created (append-only for the same audit
reason as everything else in this design) — only `status`/`resolved_*` may transition, and exactly
once (`open → resolved`), mirroring `settlement_obligation`'s own one-way transition pattern (S1 §6).

## 6. `ReconciliationService` — the matching algorithm

```
run_morning_reconciliation(market_date):
    batch = import today's three files (§3) into custodian_file_row
    holiday_check: if MarketClock says market_date is not a trading day (ADR 12),
                   do NOT run comparison logic at all — a holiday is never a break,
                   full stop, not "compared and found clean"

    # Positions
    for each (customer_id, security_id) in the union of Trueup's holdings and the file's positions:
        internal_qty = S1's current position (as of market_date, live)
        file_qty = the file's row, or absent (treated as 0, itself a mismatch if internal is nonzero)
        if internal_qty != file_qty: open reconciliation_break(position_mismatch)

    # Cash
    for each customer_id in the union of Trueup's customers and the file's cash rows:
        if S1.settled_cash(customer_id) != file's settled_cash: open reconciliation_break(cash_mismatch)

    # Transactions
    for each file transaction row: if no S1 entry has this source_event_id,
                                    open reconciliation_break(unmatched_custodian_transaction)
    for each S1 entry with an external source_event_id dated market_date: if no file row matches it,
                                    open reconciliation_break(unmatched_internal_transaction)
```

Runs as `MorningReconciliationJob` under the foundation spec's `job_run` contract (§9 of that spec) —
`cadence = 'daily'`, so a missing run for a trading day is itself detectable, the same mechanism
every other daily job already relies on.

## 7. `BreakAgingService`

```
age(break) = now() - break.opened_at
```

No new mechanism — aging is a pure function of `opened_at`, computed on read, never stored and
therefore never able to go stale. `GET /api/v1/admin/breaks` (§8) sorts by `age` descending by
default, so the oldest unresolved break is always what an adviser sees first (FR-31's "surfaced on a
screen with an aging indicator," made literal).

## 8. API contract (adviser-facing, `/api/v1/admin/*`)

- `GET /api/v1/admin/breaks?status=open` → list, sorted by age, per §7.
- `POST /api/v1/admin/breaks/<id>/resolve` → body requires `resolution_note`; sets `status =
  resolved`, `resolved_by = <acting adviser's id>`, `resolved_at = now()` — `@requires_role("adviser",
  "admin")` + `@audited` (foundation spec §7.2), since resolving a break is exactly the kind of
  privileged action that decorator exists for.

## 9. The custodian simulator (FR-33)

Built as `integrations/fake/custodian_file_adapter.py` (the foundation spec's own `integrations/
fake/` package, §3 of that spec) — reused, not duplicated, since a production-quality fake is
already the design's stated intent there. The simulator:

- Generates `positions.csv`/`cash.csv`/`transactions.csv` from Trueup's own current internal state
  by default (a "clean" run, no breaks) — the baseline the tamper/injection operations below perturb.
- `inject_tampered_position(customer_id, security_id, wrong_quantity)` — FR-32's live-fire mechanism:
  overwrites one row in the generated `positions.csv` before it's "delivered," so the next
  reconciliation run must catch exactly this one discrepancy.
- `inject_late_dividend(customer_id, security_id, amount, effective_date)` — adds a transaction row
  to `transactions.csv` with no corresponding internal entry yet, which `run_morning_reconciliation`
  correctly flags as `unmatched_custodian_transaction` — this is the intended behavior, not a bug:
  the break is what prompts investigation, which leads to posting the dividend through S5's normal
  mechanism, which is itself a restatement trigger for S6 if the affected period was already
  published.
- `inject_corrected_price(security_id, market_date, new_close)` — this doesn't go through the
  custodian file at all (closing prices are a market-data concern, S4's `daily_close`, not a
  custodian-file concern) — the simulator instead posts directly to S4's price-intake path with
  `source = 'simulated'`, clearly labelled per NFR-12.
- Every simulator-generated file/row is tagged `is_simulated = true` at the `custodian_file_row`
  level — FR-33's "clearly labelled" requirement enforced structurally, not just by naming
  convention, so a query can never accidentally mix simulated and (future) live custodian data
  without knowing it.

## 10. Edge and corner cases

1. **A market holiday that a stale hand-maintained assumption might mistake for a missing file** —
   explicitly ruled out by §6's holiday check running *before* any comparison, per ADR 12's whole
   reason for existing.
2. **A customer who closed their account between yesterday's and today's file** (zero positions,
   zero cash expected on both sides) — no break: both sides agree on zero, which is a valid,
   clean match, not a special case requiring exclusion logic.
3. **A file arriving malformed or truncated** (a real operational failure mode, not a data
   discrepancy) — surfaced as a `job_run` failure (foundation spec §9), not silently treated as "no
   custodian data today = no breaks," which would be exactly the kind of masked failure NFR-6
   prohibits.
4. **The same underlying discrepancy producing two different break rows** (e.g. a position mismatch
   that also produces a transaction mismatch for the trade that caused it) — each break type is
   independently opened by its own comparison loop; deduplicating across break types is explicitly
   not attempted in v1 (an adviser resolving one may find the other already explained by the same
   root cause, noted in `resolution_note`) — stated here as a deliberate simplification, not an
   oversight.
5. **A break resolved, then the same discrepancy reappears the next morning** (e.g. the underlying
   cause wasn't actually fixed) — opens a **new** `reconciliation_break` row; the old resolved row is
   never reopened or reused, consistent with the append-only posture and giving an accurate count of
   how many mornings a problem has recurred.

## 11. Testing strategy

- **Unit** — the three comparison loops' set-union logic (present-on-one-side-only cases), the
  holiday short-circuit.
- **Integration** — the FR-32 live-fire test itself, run as an actual integration test: generate a
  clean simulator file set, tamper exactly one position, run `ReconciliationService`, assert exactly
  one `reconciliation_break` opens and it identifies the correct customer/security/expected/actual
  values; assert `resolved_by` cannot be null on a `resolved` break at the database level (a `CHECK`
  constraint, not only application validation, per FR-44's zero-tolerance framing).
- **API** — adviser-only access to `/admin/breaks*` (a customer session must get 403, not 404, to
  avoid resource-existence leakage — consistent with the foundation spec's general error-response
  discipline), the audit log entry created on every resolve action.
- **Contract** — the custodian-file adapter's `is_simulated` tagging is exercised as part of every
  test that uses it, so a test suite accidentally treating simulated data as live would itself fail.

## 12. Open parameters (not blocking this spec)

- Whether a materiality threshold is ever introduced for position/cash breaks (v1 has none, per
  FR-32's zero-tolerance live-fire test) — an explicit future consideration, not decided here.
- The exact file-delivery mechanism (SFTP, object storage, direct API) for a *real* future custodian
  feed, as opposed to the FR-33 simulator — out of scope until a real custodian file source is
  contracted, consistent with NFR-12 treating the custodian file as "simulated is fine."
