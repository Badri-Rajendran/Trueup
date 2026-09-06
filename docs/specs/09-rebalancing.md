# S9 — Rebalancing: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-27–28
Depends on: S3 (rebalance-generated orders flow through the same `OrderService`, no parallel path),
S4 (drift evaluation reads current valuation)
Consumed by: S5 (rebalance sells are ordinary sells to `LotConsumptionService` — always FIFO, since
no investor is present to designate lots, per ADR 4)

This spec closes ADR 8's deliberately deferred parameters: band width, order minimums, fractional-
share rules, and the cash buffer.

## 1. Purpose

Rebalance each of the four model portfolios monthly against target weights (FR-27, ADR 8's calendar-
decides-when), generating orders only for holdings outside a tolerance band, respecting order
minimums, fractional-share rules, and a cash buffer (FR-28).

## 2. Non-goals

- Whether to rebalance monthly at all, or whether a tolerance band gates trading — both already
  decided, ADR 8; this spec sets the band's actual width and the other parameters ADR 8 named as
  belonging here.
- Order placement/lifecycle mechanics — S3; this spec produces order requests, S3 executes them
  identically to any customer-initiated order.
- Model portfolio *composition* (which securities, at what target weight, for each of the four
  models) — a product/investment-committee decision with real numbers this spec doesn't invent;
  `model_portfolio`/`target_weight` below is the schema that holds whatever those decisions are.

## 3. Schema

### 3.1 `model_portfolio`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | one of exactly four (FR-7) |
| `name` | text | |
| `is_active` | bool | model portfolio versioning (a stretch-ladder item, explicitly out of v1) means this spec assumes exactly one active version per model at a time |

### 3.2 `target_weight`

| Column | Type | Notes |
| --- | --- | --- |
| `model_portfolio_id` | uuid, FK | |
| `security_id` | uuid, FK | |
| `weight_pct` | numeric(5,4) | e.g. `0.2500` for 25%; `SUM(weight_pct) = 1.0` per `model_portfolio_id` is a `CHECK`-adjacent invariant, enforced the same way S1 §3.4 enforces money-sum-to-zero — a deferred constraint trigger, not application discipline alone, since this is exactly the same *cross-row* invariant shape (ADR 17's precedent applied here) |

### 3.3 `customer_model_assignment`

| Column | Type | Notes |
| --- | --- | --- |
| `customer_id` | uuid, FK, unique | one active model per customer at a time (FR-7's "buy into one of four") |
| `model_portfolio_id` | uuid, FK | |
| `assigned_at` | date | |

## 4. `DriftEvaluationService`

```
evaluate(customer_id):
    model = customer's assigned model_portfolio
    current_value = S4.value_book(customer_id, today)   # must be 'complete', not 'partial' —
                                                           # a partial valuation cannot drive a
                                                           # trading decision (composes with S4's
                                                           # own completeness flag, not re-decided)
    for each target_weight row in the model:
        current_weight = (holding's market value) / current_value.total_value
        drift = current_weight - target_weight.weight_pct
        if abs(drift) > DRIFT_BAND_PCT:   # default 5%, relative to target weight — see §5
            flag this security for rebalancing (over-weight => sell, under-weight => buy)
    also flag the CASH holding itself against its implicit target (1 - sum of security targets,
        typically 0 for a fully-invested model) using the same band
```

## 5. Band width, order minimums, cash buffer — the parameters ADR 8 deferred here

- **Drift band: `5%` relative to each holding's own target weight** (`DRIFT_BAND_PCT = 0.05`,
  meaning a 20%-target holding triggers at 19%/21%, not at a flat ±5-percentage-point band). Chosen
  relative rather than absolute because the four model portfolios' individual target weights vary in
  scale (a 5%-target holding and a 40%-target holding shouldn't share one absolute tolerance) — a
  relative band scales naturally with each holding's own size in the model, a defensible,
  industry-common convention for tolerance-banded rebalancing.
- **Order minimums: none beyond Alpaca's own fractional-share floor.** FR-28's "order minimums" are
  satisfied by the broker's own constraint (Alpaca supports fractional shares to a small notional
  floor) rather than a second, Trueup-imposed minimum — introducing an independent minimum on top
  would only ever be *more* restrictive than necessary with no stated reason to be, so none is added
  (YAGNI).
- **Fractional-share rules**: `RebalanceOrderService` always requests the *exact* fractional quantity
  needed to close the drift to zero (not to the edge of the band) — rounded to `Units`'s six decimal
  places (FR-11) — since Alpaca accepts fractional orders natively; there is no whole-share
  constraint to round toward in this design.
- **Cash buffer: `1%` of portfolio value** (`REBALANCE_CASH_BUFFER_PCT = 0.01`) held back from every
  buy order's sizing — absorbs price movement between the drift-check computation and the order's
  actual execution price, so a rebalance run doesn't generate a buy that (at the moment it actually
  fills) slightly overdraws `investable` cash due to normal intraday price movement between
  evaluation and fill.

All four are settings (`DRIFT_BAND_PCT`, `REBALANCE_CASH_BUFFER_PCT`), not hard-coded — tunable
without a spec change, consistent with every other numeric parameter in this design.

## 6. `RebalanceOrderService`

```
generate_orders(customer_id):
    flagged = DriftEvaluationService.evaluate(customer_id)
    if flagged is empty: return []   # within band on every holding — no trades, per ADR 8
    sells = [ order(security, side=sell, quantity=amount needed to close drift to zero)
              for security in flagged if over-weight ]
    # sells first, buys second — a rebalance run must not attempt to fund buys with cash that
    # hasn't yet been freed by this same run's own sells (ADR 5's investable policy already permits
    # buying against unsettled sale proceeds once the sell fill posts — this ordering is what makes
    # that composition actually happen rather than racing)
    available_for_buys = investable(customer_id) - (portfolio_value * REBALANCE_CASH_BUFFER_PCT)
    buys = [ order(security, side=buy, quantity=amount needed, capped so total buy notional
                    <= available_for_buys) for security in flagged if under-weight ]
    return sells + buys   # submitted through S3's OrderService, identical to a customer order —
                            # no designation_override (ADR 4), always FIFO on the sell side
```

Every generated order carries no `designation_override` (S5 §4's explicit rule that system-generated
sells always take the FIFO branch, since no investor is present to elect lots).

## 7. `MonthlyRebalanceJob`

Under the foundation spec's `job_run` contract, `cadence = 'daily'`... no — **`cadence` here is
genuinely monthly**, the first job in this design whose expected-run assertion is per-calendar-month
rather than per-trading-day. `job_run`'s partial unique index (foundation spec §9, ADR 13) is
`UNIQUE (job_name, market_date) WHERE cadence = 'daily'` — this job needs a third cadence value,
**`monthly`**, with its own partial unique index `UNIQUE (job_name, date_trunc('month', market_date))
WHERE cadence = 'monthly'`, so a missed monthly run is exactly as detectable as a missed daily one,
via the same mechanism generalized rather than a special case bolted on.

```
run():
    for each customer with an assigned model_portfolio:
        orders = RebalanceOrderService.generate_orders(customer_id)
        for order in orders: submit through S3's OrderService (identical path to a customer order)
```

## 8. Edge and corner cases

1. **A customer changes their assigned model mid-month, after the scheduled run already evaluated
   them under the old model** — the *next* scheduled run evaluates against whatever model is
   currently assigned at that time; no mid-month re-trigger is added (consistent with ADR 8's
   calendar-decides-when-to-check principle applied literally — a model change is not itself a
   trigger).
2. **A rebalance-generated sell is still `partially_filled` when the paired buy would otherwise be
   generated** (same run, FR-29's mid-flight condition) — `RebalanceOrderService` computes
   `available_for_buys` from `investable()` at generation time, which already accounts for the sell's
   *unsettled* proceeds once its fill posts (ADR 5); if the sell hasn't filled at all yet, its
   proceeds aren't in `investable()` yet either, so the buy is sized against whatever cash is
   genuinely available right now, never against a sell that hasn't happened.
3. **Every holding is within band** (the fully-quiescent case) — `generate_orders` returns an empty
   list; no order, no hold, no lot activity — the cheapest and most common expected outcome, not an
   edge case requiring special code, but worth stating so "no trades this month" is understood as
   success, not a null result to be treated with suspicion.
4. **A security drops out of the model entirely** (target weight goes to zero in a model update) —
   treated identically to any other under/over-weight case: a zero target with a nonzero current
   holding is a 100%-relative drift, always outside any reasonable band, generating a full-exit sell.
5. **The cash buffer itself makes a buy's sizing round to a negative or zero notional** (a customer
   near-fully invested already, with little slack) — `RebalanceOrderService` simply generates a
   smaller buy (or none) rather than erroring; a buffer constraint reducing trade size to zero is a
   valid outcome, not a failure.

## 9. Testing strategy

- **Unit** — the relative-band drift calculation (property test: a holding exactly at target has
  zero drift; a holding at exactly the band edge is the documented boundary case, `> band` triggers,
  `== band` does not); the sells-before-buys ordering; the cash-buffer sizing arithmetic.
- **Integration** — `target_weight`'s sum-to-one deferred trigger, tested the same way S1's
  ledger-balance trigger is tested (a deliberately invalid model definition must fail at `COMMIT`);
  the `monthly` `job_run` partial index actually rejects a second same-month execution.
- **API** — none new; rebalance orders flow through S3's existing endpoints and tests.

## 10. Open parameters (not blocking this spec)

- `DRIFT_BAND_PCT` (5%) and `REBALANCE_CASH_BUFFER_PCT` (1%) are tunable settings, not fixed
  constants — defensible defaults, adjustable by the investment team without a spec change.
- Model portfolio versioning (the model changes, existing customers drift against the old targets
  until reassigned) — explicitly out of v1 scope per the brief's own stretch ladder.
