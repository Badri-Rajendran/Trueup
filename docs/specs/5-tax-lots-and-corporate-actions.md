# S5 — Tax Lots & Corporate Actions: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-19–24, FR-37
Depends on: S1 (ledger — every lot event posts through `PostingService`), S3 (a fill is the trigger
event that opens/consumes a lot), S4 (`daily_close` prices unrealized gains)
Consumed by: S6 (a wash-sale adjustment or corrected cost basis is itself a restatement input), S9
(rebalance sells consume lots through this spec's default policy, no separate path), S11 (the chat
assistant's `v_tax_lots`/`v_realized_gains` views read this sub-project's data directly)

## 1. Purpose

Open a tax lot on every buy (FR-19), consume lots on sell under one declared policy — FIFO default,
specific-ID override (FR-20, ADR 4, already fully decided at the policy level; this spec makes it a
concrete service) — derive realized/unrealized gains from lot state alone, never a parallel tally
(FR-21), produce a lot-derived tax export (FR-22), handle the dividend and split lifecycle (FR-23–24),
and detect/handle wash sales arising from the platform's own automated rebalancing (FR-37, ADR 11,
same treatment: decided at the policy level, made concrete here).

## 2. Non-goals

- The FIFO-vs-specific-ID *policy decision* itself and the designation-window deadline rule — fully
  decided in ADR 4; this spec implements it, does not re-litigate it.
- The wash-sale detection *policy* (same-CUSIP-only, basis-carry mechanics) — fully decided in ADR
  11; likewise implemented, not re-decided.
- Restatement recomputation triggering — S6; this spec only guarantees that a corrected cost basis or
  a late-discovered wash sale posts a correctly-chained `superseded_by`/adjustment entry for S6 to
  react to.

## 3. Schema

### 3.1 `tax_lot`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id`, `security_id` | uuid, FK | |
| `opening_fill_execution_id` | text, FK → S3's `order_event.execution_id` | the buy fill that opened this lot — one lot per fill, never merged, even for same-day same-security fills (keeps designation-window tracking per-fill, per ADR 4) |
| `quantity_opened` | `Units` | |
| `quantity_remaining` | `Units` | decremented as sells consume it; **never negative** — a `CHECK` constraint, since a negative remaining quantity is a direct sign of a lot-consumption bug, not a valid state |
| `original_cost_basis` | `Money` | = `Price × Units` at the opening fill |
| `adjusted_basis` | `Money` | starts equal to `original_cost_basis`; carries any wash-sale-disallowed loss (ADR 11) — S1 §9 flagged this column's need, defined here |
| `acquired_at` | date | the fill's `effective_date` — FIFO orders on this |
| `designation` | enum | `unspecified` (FIFO applies) \| `specific` (investor override, ADR 4) |
| `designation_window_closes_at` | timestamptz | `min(expected_settlement_date, confirmation_event)` per ADR 4 |

### 3.2 `lot_consumption`

The record of which lot(s) a sell fill drew from — a sell fill can span multiple lots (FIFO
exhausts the oldest before moving to the next).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `closing_fill_execution_id` | text, FK → S3's `order_event.execution_id` | |
| `tax_lot_id` | uuid, FK | |
| `quantity_consumed` | `Units` | |
| `realized_gain_loss` | `Money` | = `(sale_price - adjusted_basis_per_unit) × quantity_consumed`, using the lot's basis **as of the moment of consumption** — see §5 on provisional status |
| `is_provisional` | bool | true while the lot's `designation_window_closes_at` (or the sell's own window, whichever governs) hasn't passed |

### 3.3 `wash_sale_adjustment`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `original_lot_consumption_id` | uuid, FK | the loss sale being disallowed |
| `replacement_tax_lot_id` | uuid, FK | the lot whose basis absorbs the disallowed amount (ADR 11) |
| `disallowed_amount` | `Money` | |
| `journal_entry_id` | uuid, FK | the `wash_sale_adjustment` entry_type posting (ADR 11 §S1 mechanics) |

## 4. `LotConsumptionService` — FIFO default, specific-ID override

```
consume(sell_fill, quantity_to_sell):
    if sell_fill.order.designation_override present (customer specified lots, on or before
       min(order's expected_settlement_date, confirmation_event) — ADR 4):
        lots = the specifically designated lots, in the order specified
    else:
        lots = tax_lot WHERE security_id, quantity_remaining > 0
               ORDER BY acquired_at ASC   -- FIFO, oldest first
    for lot in lots:
        take = min(lot.quantity_remaining, remaining_to_sell)
        post lot_consumption(lot, take, realized_gain_loss = (sale_price - lot.adjusted_basis/unit) * take,
             is_provisional = now() < lot.designation_window_closes_at)
        lot.quantity_remaining -= take
        remaining_to_sell -= take
        if remaining_to_sell == 0: break
    # System-generated sells (S9 rebalance) never carry a designation_override — no investor is
    # present to elect lots for them, so they always take the FIFO branch (ADR 4's explicit note).
```

**Provisional gain, made concrete (ADR 4)**: `is_provisional = true` is not cosmetic — FR-21/FR-22
both **must** read this flag and label the figure accordingly everywhere it's displayed or exported;
a query that ignores it overstates certainty about a number that can still change basis (never lot
selection) once corrections land after the window locks.

## 5. `WashSaleService` (ADR 11)

```
on_loss_sale(lot_consumption):   # fires when realized_gain_loss < 0
    window_start = lot_consumption.sale_date - 30 days
    window_end   = lot_consumption.sale_date + 30 days
    watch for a BUY fill of the SAME security (CUSIP match only, ADR 11 v1 scope) within window_end
    # window_start side: a buy that already happened before the sale is checked immediately;
    # window_end side: a buy that hasn't happened yet is checked reactively when it occurs
    if a same-CUSIP buy fill exists within [window_start, window_end]:
        replacement_lot = the tax_lot opened by that buy fill
        disallowed = min(abs(lot_consumption.realized_gain_loss), replacement_lot.original_cost_basis)
        post wash_sale_adjustment:
            journal_entry(entry_type='wash_sale_adjustment'):
                credit realized_gain_loss  by disallowed   # reverses the loss about to be recognized
                debit  replacement_lot.position_cost  by disallowed
            replacement_lot.adjusted_basis += disallowed   # carried into the replacement's basis
            lot_consumption.realized_gain_loss += disallowed   # the sale's own recognized loss shrinks
```

The reactive side (a replacement buy arriving *after* the loss sale, possibly in a later month or
after a restatement already touched the original sale) is checked every time a new buy fill posts,
scanning open `lot_consumption` loss rows within that buy's own trailing 30-day window — this is what
ADR 11 means by "composes cleanly with ADR 1's and ADR 6's existing machinery... no new temporal
reasoning required": the check is symmetric and re-runs naturally whenever either side of the pair
newly exists, rather than needing a scheduled sweep.

## 6. `CorporateActionService` — dividends and splits

### 6.1 Dividend (FR-23)

```
declared  → post nothing yet (an announcement, no economic event)
ex_date   → post dividend_receivable (S1 role, extending the account enum): debit dividend_receivable,
            credit dividend_income — entitlement recognized, cash not yet moved
pay_date  → post dividend: debit cash, credit dividend_receivable — cash finally arrives, days later
```

Both legs are ordinary S1 postings (no new ledger mechanism); the two-step split is what makes the
"days later" gap (brief's own framing) representable at all, rather than pretending the dividend
resolves atomically on ex-date.

### 6.2 Split (FR-24) — an entry with no money legs

```
2-for-1 split:
    for each tax_lot open in the security:
        lot.quantity_opened   *= 2
        lot.quantity_remaining *= 2
        lot.original_cost_basis, lot.adjusted_basis  unchanged (per-unit basis halves implicitly,
            since the same total basis now spans twice the units)
    post a units-only journal entry (S1 §3.4's own worked example) — position_units doubles,
    no money postings at all
```

Value and return are structurally unable to move (S1's schema itself proves it, per S1 §3.4's own
framing) — this spec's only addition is the lot-quantity-doubling rule, since S1 didn't own tax lots.

## 7. Edge and corner cases

1. **A sell that spans lots with different designation states** (one FIFO, one specifically
   designated from an earlier partial sell of the same security) — each `lot_consumption` row tracks
   its own lot's `is_provisional` independently; a single sell fill can produce a mix of provisional
   and locked realized amounts, and FR-21/22 must sum them correctly while preserving the
   per-lot provisional flag for display.
2. **A wash sale where the replacement buy is itself later sold at a loss within another 30-day
   window** (a chained wash sale) — handled without special-casing, since `on_loss_sale` re-fires
   symmetrically for the new loss sale against its own trailing window; the adjusted basis carried
   forward from the first adjustment is simply the replacement lot's basis going into the second
   check.
3. **A corrected closing price restates a period whose lots were consumed under FIFO** — basis-only
   correction (a new posting adjusting `original_cost_basis` via `superseded_by`), lot selection is
   never revisited, per ADR 4's core guarantee.
4. **A split on a security with an open, still-provisional lot consumption** (a sell fill happened,
   designation window hasn't closed, then a split arrives) — the split doubles `quantity_remaining`
   on the *lot*, which is independent of the *consumption* row already recorded against the
   pre-split quantity; no interaction, since consumption already happened against the pre-split units
   and basis and a split changes neither value nor return (§6.2).
5. **A dividend's ex-date and a sell of the same security fall on the same day** — entitlement
   (ex-date posting) and the sell's lot consumption are independent postings against different
   accounts; whether the customer still held the security *as of* ex-date (the actual entitlement
   rule) is a S3/broker-timing detail this spec assumes the fill sequence already resolves correctly
   (the broker, not Trueup, determines entitlement eligibility).
6. **Zero remaining lots but a sell fill arrives anyway** (a reconciliation-worthy anomaly — should
   never happen if S3's holdings tracking is correct) — `LotConsumptionService` raises rather than
   silently creating a negative-quantity lot; this becomes an S7 reconciliation break, not a silently
   absorbed data error.

## 8. Testing strategy

- **Unit** — FIFO ordering property test (oldest lot always consumed first absent an override);
  wash-sale disallowed-amount arithmetic including the `min(loss, replacement_basis)` cap; the
  split's quantity-doubling with basis-preservation invariant.
- **Integration** — the `quantity_remaining >= 0` `CHECK` constraint actually rejects an
  over-consumption attempt at the database level, not just in application logic; the wash-sale
  reactive check correctly fires when the replacement buy is posted in a transaction independent of
  the original sale's.
- **Contract** — none (this spec has no external integration of its own).

## 9. Open parameters (not blocking this spec)

- Exact tax-export file format (FR-22) — a presentation-layer detail for S8, not this spec's schema.
- Whether a chained wash sale (edge case 2) needs its own disclosure line in the export beyond the
  standard adjusted-basis figure — a tax-reporting UX question deferred to S8/FR-22's own spec.
