# S4 — Valuation & Returns: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-14–18
Depends on: S1 (ledger — positions and cash), ADR 12 (market calendar/timezone), ADR 3 (TWR
methodology, decision-level — this spec makes it concrete)
Consumed by: S5 (realized/unrealized gains use `daily_close`), S6 (restatement recomputes exactly
the sub-periods this spec's algorithm identifies), S9 (drift evaluation reads current valuation),
S11 (the chat assistant's `v_period_return`/`v_customer_balance` views read this sub-project's data)

## 1. Purpose

Value the whole book daily against closing prices (FR-14), handle a missing close or a stale price
honestly rather than masking it (FR-15/NFR-6), report one declared return methodology (FR-16) such
that cash flows never pollute it (FR-17), and expose balance/return/history to the customer (FR-18).
ADR 3 already decided *what* the methodology is (TWR, sub-periods broken at every flow); this spec
decides exactly *how* it is computed, stored, and re-computed.

## 2. Non-goals

- The as-published/as-corrected snapshot mechanism itself — S6; this spec produces the live figures
  S6 snapshots, it does not implement the snapshot table.
- Tax lots and realized/unrealized gains — S5, though both read this spec's `daily_close` table.
- Market-calendar source and timezone anchoring — already fully decided, ADR 12; this spec is a
  consumer of `MarketClock`, not a second implementation of it.

## 3. Schema

### 3.1 `daily_close`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `security_id` | uuid, FK | |
| `market_date` | date | America/New_York trading day (ADR 12) |
| `close_price` | `Price` | |
| `source` | enum | `live` \| `simulated` (NFR-12's "market data live or simulated," clearly labelled) |
| `status` | enum | `confirmed` \| `stale` \| `missing` — FR-15's honest-degradation states, not silently defaulted |
| `recorded_at` | timestamptz | when this system learned it (ADR 1's pattern, applied to price data too, since a corrected close is itself a restatement trigger for S6) |

`UNIQUE (security_id, market_date, recorded_at)` — a corrected close for the same `market_date` is a
**new row**, never an `UPDATE`, since S6's restatement mechanism depends on being able to see what the
close was *as of* any prior watermark (ADR 1's bitemporal pattern extended to price data, not just
ledger postings).

### 3.2 `valuation_run`

One row per `market_date` the `DailyValuationJob` (foundation spec §9) processes — the "did today's
valuation actually run and complete" assertion, the same shape as that spec's `job_run` but scoped to
per-security-close-completeness rather than job execution alone:

| Column | Type | Notes |
| --- | --- | --- |
| `market_date` | date, PK | |
| `securities_expected` | int | every security any customer holds a position in as of this date |
| `securities_confirmed` | int | how many got a `status = confirmed` close |
| `status` | enum | `complete` (all confirmed) \| `partial` (some missing/stale) \| `pending` |

A `partial` `valuation_run` is a reconciliation-visible condition (surfaced to S7/S8), not a silent
best-effort valuation — FR-15's "surface the condition, never silently substitute" applied at the
whole-book level, not just per-security.

### 3.3 `security` — the instrument master

Three tables across three specs carry a `security_id` foreign key — `account.security_id` (S1 §3.1),
`order.security_id` (S3 §3.1), and `daily_close.security_id` (§3.1 above) — but no spec defined what
they point at. It is defined here because S4 is the sub-project that actually resolves a security to
a price, and every other consumer only needs its identity.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | the `security_id` every other table references |
| `symbol` | text, unique | the ticker as Alpaca knows it — the join key to every provider |
| `name` | text | human-readable, for display only; never used for matching |
| `asset_class` | enum | `equity` \| `bond` (NFR-8's US-listed equities and bonds, nothing wider) |
| `status` | enum | `active` \| `inactive` — a delisted or halted security stays queryable, since positions and history still reference it |
| `created_at` | timestamptz | |

Deliberately minimal. Exchange, CUSIP, fractional-share eligibility, and corporate-action metadata
are **not** here: `requirements.md` leaves fractional-share-ineligible handling explicitly deferred,
and S5 owns corporate actions. A security is added by an operator or seeded from a model portfolio's
target weights (S9) — there is no customer-facing endpoint that creates one, so nothing here is
user-supplied input.

### 3.4 `market_calendar_cache`

Named in the foundation spec §3's package layout (`models/marketdata/market_calendar_cache`) but
never given a schema. `MarketClock` (ADR 12) reads it; `CalendarPort → Alpaca` populates it.

| Column | Type | Notes |
| --- | --- | --- |
| `market_date` | date, PK | America/New_York trading day |
| `is_trading_day` | bool | the FR-40 / §6 holiday-vs-missing distinction depends on this being *known*, not inferred |
| `session_open_at` | timestamptz, nullable | null on a non-trading day |
| `session_close_at` | timestamptz, nullable | null on a non-trading day; early closes are real values, not assumed 4pm |
| `source` | enum | `live` \| `simulated` (NFR-12's labelling rule, applied to calendar data too) |
| `recorded_at` | timestamptz | when this system learned it |

A cache miss is **not** treated as "not a trading day." An absent row means the calendar has not been
fetched for that date, which is an operational condition to surface — silently reading a missing row
as a holiday would suppress exactly the missed-valuation alert §6 and S0 §10.7 exist to raise.

### 3.5 `sub_period_return`

§5 names this table and its key in prose, but §3 omitted it. ADR 3's claimed property — that a
correction "touches exactly one sub-period" — is only literally true if each sub-period's return is
stored rather than recomputed end-to-end, so it belongs in the schema, not only in the algorithm.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `sub_period_start` | date | |
| `sub_period_end` | date | |
| `return_pct` | NUMERIC(18,10) | `r_i` for this sub-period; wider than `Money`'s 4dp because a linked product compounds rounding error |
| `value_begin`, `value_end` | `Money` | retained so a restatement can be audited, not just recomputed |
| `flow_amount` | `Money` | the external flow at `sub_period_end`, per §5's formula |
| `is_provisional` | bool | true when computed from a `partial` `valuation_run` (§8 case 4) |
| `recorded_at` | timestamptz | |

`UNIQUE (customer_id, sub_period_start, sub_period_end, recorded_at)` — a restated sub-period is a
**new row**, never an `UPDATE`, matching `daily_close`'s bitemporal treatment in §3.1 and ADR 1's
pattern. `TwrService` reads the latest `recorded_at` per sub-period; S6 pins to the watermark that
was live at publication.

## 4. `ValuationService`

`value_book(customer_id, as_of_date)`:

```
for each position the customer holds as of as_of_date:
    close = daily_close WHERE security_id, market_date = as_of_date, status = 'confirmed',
            ORDER BY recorded_at DESC LIMIT 1   -- the latest known-good close for that day
    if no confirmed close exists:
        mark this security's contribution as 'stale' or 'missing' (per daily_close.status)
        -- FR-15: do NOT substitute the prior day's close silently
    value += units * close_price   -- Price * Units -> Money (ADR 16), never a bare multiplication
return { total_value, as_of_date, completeness: 'complete' | 'partial' }
```

A `partial` valuation is still returned (a customer should not see nothing), but every consumer —
S8's balance screen, S11's chat assistant — must surface the `completeness` flag, never presenting a
partial valuation as if it were whole. This is the concrete mechanism behind NFR-6.

## 5. `TwrService` — ADR 3's algorithm made concrete

```
compute_twr(customer_id, period_start, period_end):
    flows = external cash flows (deposit/withdrawal journal entries, S1) strictly between
            period_start and period_end, ordered by effective_date
    boundaries = [period_start] + [f.effective_date for f in flows] + [period_end]
    sub_periods = consecutive pairs of boundaries
    for (v_begin, v_end) in sub_periods:
        r_i = (value_book(v_end) - value_book(v_begin) - flow_amount_at(v_end)) / value_book(v_begin)
    twr = product(1 + r_i for r_i in sub_period_returns) - 1
    return twr
```

**Restatement composability (why this is the algorithm and not a shortcut)**: a corrected close for
one day inside one sub-period only changes that sub-period's `r_i`; the geometric product is
re-linked from the stored per-sub-period returns, not recomputed end-to-end — this is precisely ADR
3's claimed property ("touches exactly one sub-period"), and this spec is what makes that literally
true rather than aspirational. `sub_period_return` is therefore its own stored row (not only the
final linked TWR), keyed by `(customer_id, sub_period_start, sub_period_end, recorded_at)` —
S6 restates by recomputing one such row and re-linking, never by recomputing the whole period.

## 6. Handling a missing or stale close (FR-15, NFR-6)

- **Missing** (no close arrived at all by the valuation cutoff): `daily_close.status = 'missing'`
  is inferred by absence, not stored as a row — `valuation_run.securities_confirmed` undercounts,
  which is what marks the run `partial`.
- **Stale** (a close arrived but is flagged suspect by the market-data provider, or a later close for
  an earlier date arrives after this date's valuation already ran): `status = 'stale'`, and any
  valuation computed from it is retroactively part of a future restatement once a `confirmed`
  replacement arrives — composes with §5's restatement mechanism, no new logic needed.
- **FR-40's distinction is inherited, not re-derived**: a market holiday (per ADR 12's calendar) is
  never treated as `missing` — `valuation_run` for a non-trading day is simply not expected to exist,
  full stop, checked against the same calendar S7 uses for its own break-vs-holiday distinction.

## 7. API contract

- `GET /api/v1/valuation/balance` → current balance, `completeness` flag (FR-18).
- `GET /api/v1/valuation/returns?period=` → the linked TWR for a period, always labelled live
  (S6 owns the as-published variant).
- `GET /api/v1/valuation/history` → transaction history (FR-18) — reads S1's ledger directly via the
  `as_of`-aware repository (foundation spec §5), defaulting to live.

## 8. Edge and corner cases

1. **A customer with zero positions on a valuation date** (fully in cash) — `value_book` returns the
   cash balance alone; TWR for a period with no positions and no flows is `0%`, not undefined or an
   error.
2. **A flow lands exactly at a sub-period boundary already created by another flow the same day** —
   boundaries are deduplicated by `effective_date`; two same-day flows produce one sub-period break,
   not two degenerate zero-length sub-periods.
3. **The very first sub-period of a customer's lifetime** (`v_begin` = the deposit that opened the
   account) — `r_i` for that sub-period is `0` by construction (`value_book(v_begin)` already
   reflects the deposit, so `V_end - V_begin - F` correctly nets to just the market movement after
   funding, per ADR 3's formula applied literally).
4. **A `partial` valuation_run's effect on TWR** — a sub-period whose `v_end` lands on a `partial`
   day computes `r_i` from whatever confirmed closes exist and is itself flagged provisional; once
   the missing close arrives, that sub-period recomputes exactly like any other restatement (§5).
5. **Two corrected closes for the same `market_date` in quick succession** — `recorded_at` orders
   them; `ValuationService` always reads the latest `recorded_at`'s `confirmed` row, and S6's
   as-published views pin to whichever watermark was live at publication regardless of how many
   corrections followed.

## 9. Testing strategy

- **Unit** — `TwrService`'s sub-period-break logic (property-based: arbitrary flow sequences must
  produce a return unaffected by flow timing, per FR-17), the missing-vs-stale-vs-holiday
  classification.
- **Integration** — `value_book`'s `Price * Units` computation against real `NUMERIC` columns
  (rounding behavior matches production exactly, per the foundation spec's real-Postgres testing
  rule); a corrected close correctly re-links only the affected sub-period, verified by asserting
  every *other* sub-period's stored row is byte-for-byte unchanged.
- **API** — the `completeness` flag is never dropped between the service layer and the response
  schema (a `views/` contract test, not just a service-level unit test).

## 10. Open parameters (not blocking this spec)

- The exact valuation cutoff time each day (how long to wait for a close before marking it
  `missing`) — an operational tuning parameter for `DailyValuationJob`, not an architectural one.
- Whether a dollar-gain figure (ADR 3's "additive, not decided here" alternative) is shown alongside
  TWR — deferred to S8.
