# S1 — Ledger & Units Core: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-11, FR-12, FR-13, NFR-1, NFR-2, NFR-3
Depends on: nothing (this is the foundation)
Consumed by: S2–S9 (every later sub-project reads this ledger)

## 1. Purpose

Get the two-dimension problem right before any UI (brief line 64). This spec defines the
account/journal/posting schema that is Trueup's economic source of truth, the settlement
obligation model that tracks the T+1 gap without physically moving money, and the two cash policy
functions everything else in the system reads instead of a stored "balance."

Everything here follows the core principle in [`docs/architecture.md`](../../architecture.md):
**append-only truth → derived projection → assert the two agree.**

## 2. Non-goals (explicitly out of this spec)

- Tax lots, FIFO/specific-ID consumption, realized/unrealized gains — **S5**.
- Order lifecycle, fills, approval holds — **S3**. This spec defines the `holds` and
  `open_buy_commitments` *inputs* the cash policy functions need, but does not implement the table
  that produces them.
- Returns, valuation, TWR — **S4**.
- Reconciliation, custodian file — **S7**.
- No HTTP surface. S1 has no controllers or views (per `backend/CLAUDE.md`'s MVC layering) — it is
  a foundation module under `app/models/` consumed in-process by every later sub-project.

## 3. Schema

### 3.1 `account`

One row per (customer, role, security) combination the ledger needs to post against. Each account
has exactly one **dimension** — `money` or `units` — enforced at the posting level (§3.3).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, nullable | null only for house accounts (e.g. `fees_expense`) |
| `security_id` | uuid, nullable | set only for `position_units` / `position_cost` roles |
| `role` | enum | `cash`, `customer_equity`, `position_units`, `position_cost`, `fees_expense`, `dividend_income` — extensible; S5 adds `dividend_receivable`, `realized_gain_loss`; S10 adds `fees_accrued_payable`, `fee_revenue_accrued`, `fee_revenue_collected` (ADR 10) |
| `dimension` | enum | `money` \| `units`, determined by `role`, never independently settable |
| `currency` | text | `'USD'` always (NFR-8) — kept explicit rather than assumed, so a future multi-currency change is additive |

### 3.2 `journal_entry`

The bitemporal unit of correction (per ADR 1). A correction supersedes the whole entry, not
individual legs — a trade's cash leg and units leg are corrected together or not at all.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `entry_type` | enum | `trade_buy`, `trade_sell`, `deposit`, `withdrawal`, `dividend`, `split`, `fee_adjustment`, `correction` |
| `effective_date` | date | when it happened |
| `recorded_at` | timestamptz | server-set on insert, monotonic, never updated |
| `superseded_by` | uuid, nullable, FK → `journal_entry.id` | correction chain (ADR 1) — see note below |
| `supersedes_reason` | text, nullable | e.g. "corrected closing price for 2026-09-01" |
| `source_event_id` | uuid, unique, FK → inbound event | idempotency tie-in to intake (ADR 7's pattern, reused here) |
| `memo` | text, nullable | |

**`superseded_by` vs. `correction`, disambiguated:** any `entry_type` can be corrected — a
corrected `trade_buy` stays `entry_type = trade_buy` and is superseded via `superseded_by`, so a
buy's correction is still recognizable as a buy. `entry_type = correction` is reserved for a
standalone book adjustment that does **not** supersede any specific prior entry (e.g. a manual
accounting adjustment). The two mechanisms are not alternatives for the same case: `superseded_by`
is *how* any entry gets corrected; `correction` is *what kind* of entry a freestanding adjustment
is.

### 3.3 `posting`

The legs. Each row moves **exactly one dimension** on **exactly one account** — this is the
mechanical enforcement of NFR-3 (units and money never conflated): the schema makes mixing them a
constraint violation, not a code-review concern.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `journal_entry_id` | uuid, FK | |
| `account_id` | uuid, FK | |
| `customer_id` | uuid, nullable | **denormalized from `account.customer_id`, trigger-set — see below. Never written by application code.** |
| `amount_money` | NUMERIC(18,4), nullable | signed |
| `quantity_units` | NUMERIC(28,6), nullable | signed, six decimal places per FR-11 |

`CHECK`: exactly one of `amount_money` / `quantity_units` is non-null. Matching the non-null
column against the target account's `dimension` is a **cross-table** condition — a plain `CHECK`
can only see columns in its own row, so it cannot inspect `account.dimension`. Enforced instead by
the `BEFORE INSERT` trigger below, alongside the `customer_id` denormalization.

**`posting_denormalize_and_validate()` — `BEFORE INSERT` trigger on `posting`:**

```sql
CREATE FUNCTION posting_denormalize_and_validate() RETURNS trigger AS $$
DECLARE
  acct RECORD;
BEGIN
  SELECT customer_id, dimension INTO acct FROM account WHERE id = NEW.account_id;

  NEW.customer_id := acct.customer_id;

  IF acct.dimension = 'money' AND NEW.quantity_units IS NOT NULL THEN
    RAISE EXCEPTION 'posting.quantity_units set against a money-dimension account (%)', NEW.account_id;
  ELSIF acct.dimension = 'units' AND NEW.amount_money IS NOT NULL THEN
    RAISE EXCEPTION 'posting.amount_money set against a units-dimension account (%)', NEW.account_id;
  END IF;

  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER posting_before_insert
  BEFORE INSERT ON posting
  FOR EACH ROW EXECUTE FUNCTION posting_denormalize_and_validate();
```

Two purposes in one trigger, both needed because `posting` has no other way to see across to
`account`: (1) **`customer_id` denormalization** — S0 §7.3's tenant-isolation RLS policy filters
`posting` directly on `customer_id` for query performance (no join on every row-security check);
setting it here, never from application code, makes it impossible for `PostingService` to write a
posting whose `customer_id` disagrees with its `account_id`. (2) **Dimension validation** — the
`CHECK` this spec's schema needs but Postgres cannot express as a single-row constraint.

This is a synchronous, per-row, non-deferred trigger — distinct from and compatible with §6/ADR
17's `DEFERRABLE INITIALLY DEFERRED AFTER INSERT OR UPDATE OR DELETE` trigger, which enforces the
cross-row zero-sum invariant at `COMMIT`. Both fire on every posting insert; they check different
things at different times.

### 3.4 Invariant: money postings sum to zero per entry

`COALESCE(SUM(posting.amount_money) FILTER (WHERE journal_entry_id = :entry), 0) = 0`

The `COALESCE` matters: an entry with **no** money postings at all (the split example below) has
`SUM(amount_money)` evaluate to `NULL`, not `0`, in SQL — without it the invariant would reject the
very entry type it needs to describe correctly. A units-only entry trivially satisfies "zero money
moved" by having moved none.

This is a **cross-row** invariant — it sums every posting belonging to one entry, not one row in
isolation — so it cannot be written as a `CHECK` constraint the way §3.3's dimension rule can be.
§6 defines the actual enforcement mechanism (a deferred constraint trigger, ADR 17); this section
states the property, §6 states how the database guarantees it.

This is standard double-entry, restricted to the money dimension. Units postings are **not** part
of this sum — their counterparty is the external market, which Trueup does not book as an internal
account (a deliberate simplification: FR-30/S7 reconciles against the custodian file for that side,
so a full internal broker-side ledger would duplicate work reconciliation already does).

Worked examples:

```
Buy 10 AAPL @ $150 + $1 fee
  position_units:AAPL   quantity_units  +10.000000        (units leg, not in the money sum)
  position_cost:AAPL    amount_money    +1500.00
  fees_expense          amount_money       +1.00
  cash                  amount_money   -1501.00
  money sum: 1500 + 1 - 1501 = 0                    ✓

Deposit $1,000
  cash              amount_money   +1000.00
  customer_equity    amount_money  -1000.00
  money sum: 1000 - 1000 = 0                          ✓

2-for-1 split (units-only entry, FR-24)
  position_units:AAPL   quantity_units   +<prior units>
  (no money postings at all — value and return must not move, FR-24 —
   and this entry_type has no money legs to sum, which is the schema
   itself proving the split cannot touch value)
```

`customer_equity` is the counterparty for deposits/withdrawals (increases customer_equity credit
on deposit, i.e. the customer's contributed capital) — it also gives S4/ADR-3's optional "net
contributions" figure a natural source, without S1 needing to know anything about returns.

Sells, dividend receivable/pay-date splitting, and realized gain/loss legs are **S5's** to define,
since they require lot cost basis this spec does not compute. S1 guarantees only that whatever S5
posts still balances to zero in the money dimension — the invariant is enforced generically at the
schema/trigger level, not per entry_type.

### 3.5 `customer_cash_lock`

The foundation spec §10.1 requires every cash-consuming operation — order hold (S3), withdrawal
(S2), fee charge (S10) — to evaluate its cash-policy check and write its effect inside one
`UnitOfWork` transaction holding `SELECT ... FOR UPDATE` on "the same canonical per-customer
cash-lock row." That row is defined here, since S1 owns the cash policy those operations serialize
against.

| Column | Type | Notes |
| --- | --- | --- |
| `customer_id` | uuid, PK, FK → `customer.id` | one row per customer, created with the customer |

Deliberately payload-free: it exists to be locked, not to be read. Locking a dedicated row rather
than the `customer` row itself keeps cash serialization from blocking unrelated customer writes (a
KYC status transition, a profile change) that have nothing to do with cash — and makes the lock's
purpose self-evident at every call site, rather than an unexplained `FOR UPDATE` on a general-purpose
table.

`CashPolicyService` exposes the acquisition as a single method so no caller hand-writes the lock
query; taking it is a precondition of `withdrawable`/`investable` being used for a *write* decision,
not for a read-only display.

## 4. Settlement obligations (FR-13, ADR 2)

The ledger posts the **economic** fact immediately at trade/deposit time — cash already moves in
the postings above the moment the entry is recorded. `settlement_obligation` is a **separate**
table tracking whether the custodian has actually confirmed that movement. It never posts to the
ledger on a state transition (ADR 2: no physical transfer of money internally).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `journal_entry_id` | uuid, FK | the entry whose cash leg this obligation tracks |
| `account_id` | uuid, FK | the cash account affected once confirmed |
| `amount_money` | NUMERIC(18,4) | mirrors the journal entry's cash leg |
| `expected_settlement_date` | date | **scheduling/risk input only — never the trigger** (ADR 2) |
| `status` | enum | `pending` → `confirmed` \| `failed`, one terminal transition, never reopened |
| `confirmed_at` / `failed_at` | timestamptz, nullable | set only by an external confirmation event |
| `failure_reason` | text, nullable | populated on `failed` (FR-6: bounced deposit) |
| `source_event_id` | uuid, unique, FK → inbound event | idempotency |

Not every entry needs one (e.g. an internal fee adjustment can be treated as instantly settled);
every entry that moves cash against an *external* counterparty (deposit, withdrawal, trade,
dividend pay-date) does.

## 5. Cash policy functions (ADR 5)

Pure functions, nothing stored. Inputs are named explicitly so the S3 dependency is visible rather
than implicit:

```
settled_cash(customer)
  = SUM(posting.amount_money) on customer's cash account
    WHERE posting.journal_entry_id IN (
      entries with no obligation required, OR
      entries whose settlement_obligation.status = 'confirmed'
    )

unsettled_sale_proceeds(customer)
  = SUM(amount_money) over settlement_obligation
    WHERE status = 'pending' AND journal_entry.entry_type = 'trade_sell'

unsettled_deposit_proceeds(customer)
  = SUM(amount_money) over settlement_obligation
    WHERE status = 'pending' AND journal_entry.entry_type = 'deposit'

withdrawable(customer)  = settled_cash(customer) - holds(customer)
investable(customer)    = settled_cash(customer)
                         + unsettled_sale_proceeds(customer)
                         + unsettled_deposit_proceeds(customer)
                         - open_buy_commitments(customer)
                         - holds(customer)
```

**`unsettled_deposit_proceeds`, added alongside `unsettled_sale_proceeds`:** S2 states plainly that
a deposit is available for `investable` purposes immediately, before its `settlement_obligation`
confirms, "exactly as any other unsettled inflow" — the original formula had a term for one
unsettled inflow (a pending sale) but not the other (a pending deposit), which would have made a
fresh deposit uninvestable until T+1 confirmation, contradicting S2 outright. `withdrawable` is
deliberately **not** given the same term — ADR 5 is explicit that unsettled proceeds of any kind
are investable but never withdrawable, so this asymmetry between the two policy functions is by
design, not an oversight to reconcile.

`holds(customer)` and `open_buy_commitments(customer)` are **owned by S3** (order
awaiting-approval and submitted-but-unfilled holds respectively) — S1 defines the contract
(a queryable total per customer) and composes it; it does not implement the holds table. This
keeps the ledger core free of order-lifecycle concerns while still producing a correct policy
result once S3 exists.

### 5.1 Free-riding guard

```
flag_if(
  a sell posts against position_units:X, AND
  the buy that opened the consumed units has a settlement_obligation
  still in status='pending' at the time of the sell
)
```

The join is over data this spec already produces (§4) plus the lot-to-obligation link S5 adds when
it implements lot consumption — noted here as an S5 dependency, not built in S1.

## 6. Append-only enforcement

- `journal_entry` and `posting`: no `UPDATE` or `DELETE` grant for the application role at the
  database level; a correction is always a new `journal_entry` with `superseded_by` set on the row
  it corrects. This is a hard DB-level guarantee, not just application discipline, per NFR-1.
- `settlement_obligation`: `status` may transition exactly once from `pending` to a terminal state;
  enforced by a `CHECK`/trigger rejecting any update where the current status is already terminal.
  This is a state machine, not a ledger — it is allowed to mutate once, unlike `posting`.
- **§3.4's money-sum-to-zero invariant is a *cross-row* property** — a plain `CHECK` constraint
  cannot express it, since it spans every posting in one journal entry, not one row. It is enforced
  by a Postgres `DEFERRABLE INITIALLY DEFERRED` constraint trigger on `posting` (`AFTER INSERT OR
  UPDATE OR DELETE`) that sums `amount_money` per affected `journal_entry_id` and raises if non-zero,
  firing once at `COMMIT` — after every leg of a multi-row posting is written, not per individual
  insert. This closes the one gap in this section's otherwise-complete DB-level guarantee: without
  it, the zero-sum invariant would hold only as long as `PostingService` and every future writer
  gets it right, with nothing underneath to catch a mistake. See ADR 17.

## 7. Testing strategy

Per `backend/CLAUDE.md`: Pytest, mirrored across `test_models.py` for this module; each invariant
below is a direct assertion, not an integration-level inference:

1. **Money sums to zero per entry** — property-based test posting arbitrary valid entries;
   assert the invariant on every `entry_type` example in §3.4. Separately, assert the §6/ADR 17
   trigger itself: a transaction that inserts a deliberately out-of-balance set of postings must
   fail at `COMMIT`, not merely fail an application-level check — this is the test that proves the
   database, not just `PostingService`, enforces the invariant.
2. **Units never cross into money** — assert the `CHECK` constraint rejects a posting with both
   columns set. Assert `posting_denormalize_and_validate()` (§3.3) rejects a posting whose
   non-null column doesn't match its account's dimension, and separately assert it sets
   `posting.customer_id` from the target account regardless of what (if anything) the insert
   statement supplied — the trigger's denormalization, not the caller, is the source of truth.
3. **Append-only** — assert `UPDATE`/`DELETE` against `journal_entry`/`posting` fail at the DB
   layer; assert a correction round-trip (`superseded_by` chain) leaves the original row byte-for-
   byte unchanged.
4. **Settlement never mutates the ledger** — assert that transitioning a `settlement_obligation`
   from `pending` → `confirmed` produces zero new `posting` rows.
5. **Cash policy functions** — table-driven tests for `withdrawable`/`investable` covering: no
   obligations, one pending sell, one pending deposit (asserting it counts toward `investable` but
   not `withdrawable` — the asymmetry §5 states explicitly), one failed deposit (FR-6), and a
   free-riding scenario.

Two invariants named in the FR/NFR catalogue belong to later sub-projects and are **not** tested
here: `derive(period, publish_watermark) == snapshot` (S6, ADR 6) and
`order_projection == fold(order_events)` (S3, ADR 7).

## 8. Migration

One Alembic revision per table (`account`, `journal_entry`, `posting`, `settlement_obligation`),
generated via `uv run alembic revision --autogenerate`, per `backend/CLAUDE.md`. The `CHECK`
constraints in §3.3, the revoked `UPDATE`/`DELETE` grants in §6, the `posting_before_insert`
trigger (§3.3), and the `ledger_balance` deferred constraint trigger (§6, ADR 17) must all be part
of the migration — hand-written SQL added alongside the autogenerated schema, not left to
application-layer discipline alone.

## 9. Open parameters (not blocking S1, resolved by consuming sub-projects)

- Exact `role` enum growth (dividend_receivable, realized_gain_loss, withholding_payable) — S5.
- `holds` / `open_buy_commitments` table shape — S3.
- Whether `customer_equity` is exposed as a customer-facing "net contributions" figure — S4/S8.
- Performance-fee accounts (`fees_accrued_payable`, `fee_revenue_accrued`, `fee_revenue_collected`)
  and the fee-lifecycle state machine (accrue → charge → dunning) — S10 (ADR 10). S1's postings and
  zero-sum invariant apply unchanged; S10 introduces no new ledger mechanism.
