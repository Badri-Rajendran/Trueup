# 10 — Performance fee: TWR + high-water-mark, charged via Stripe Billing, locked to as-published

## Status

Accepted

## Context

The brief's stretch ladder names "performance fee accrual, computed daily, charged monthly" as
explicitly out of core v1 scope. The user promoted it to core v1 (2026-09-04) and decided Stripe is
the payment gateway for it. This is genuinely new architectural surface with no existing sub-project
— and it touches three already-decided pieces that must not be contradicted: the return methodology
(ADR 3, TWR), the ledger (ADR 1, bitemporal append-only), and restatement (ADR 6, as-published vs.
as-corrected). The load-bearing risk, not addressed by simply "adding Stripe billing": a fee charged
this month, based on this month's return, can later be invalidated by the exact mechanism this
platform exists to support — a correction that restates the period's return (ADR 6) *after* the fee
was already charged. Left undesigned, that is a real hole in the platform's most differentiating
feature, not a hypothetical edge case.

## Decision

### Basis: TWR-derived gain with a high-water-mark, not a flat AUM fee

"Performance fee" means charging on gains, not simply a percentage of assets under management. The
fee basis reuses **ADR 3's already-decided TWR** rather than inventing a second, competing notion of
return — the customer's dollar-equivalent gain over a period is derived from the same TWR figure
already computed for reporting. A per-customer **high-water-mark** (the highest previously-billed
cumulative value) ensures a period's fee is never charged twice on the same gain — a drawdown
followed by a recovery back to the prior peak accrues no new fee until the customer's value exceeds
that peak. This is the standard, defensible construction for a performance (as opposed to AUM) fee.
Fee rate and accrual-day-count convention are parameters for S10's own spec, not decided here.

### Daily accrual and monthly charge are two separate ledger events

- **Daily accrual** posts a `fee_accrual` journal entry (ADR 1's existing mechanism — no new
  posting machinery) with two money legs summing to zero (S1's invariant): `fees_accrued_payable`
  (a new, customer-scoped liability account) is debited, `fee_revenue_accrued` (a house account) is
  credited. Nothing customer-facing changes yet — this only records that a liability now exists.
- **Monthly charge** fires against the customer's **Stripe-linked payment method** — never the
  Alpaca cash balance and never a position sale. A successful charge posts `fee_charge`: debit
  `fee_revenue_accrued` / credit `fee_revenue_collected`, and clear `fees_accrued_payable`. The
  investment ledger (`cash`, `customer_equity`, `position_*` accounts) is never touched by fee
  postings — this is a parallel money flow through the same ledger mechanism, on entirely separate
  accounts. Paying a performance fee must never force a sell-to-cover or reduce investable cash.
- A **failed charge** does not reverse the accrual — the liability remains posted and owed; a
  defined retry/dunning state (FR-48) governs when it is re-attempted, tracked outside the ledger
  (an S10-owned state, not a new `entry_type`).

### The fee locks to the as-published figure, not the live one

At charge time, the fee basis locks to the period's **as-published** snapshot (ADR 6's
`recorded_at <= publish_watermark` figure) — not whatever the live, as-corrected figure says at that
moment. A later restatement of that period (ADR 6, `derive(period, now) != snapshot`) does **not**
reopen or adjust an already-charged fee. This mirrors two patterns already established elsewhere in
this design rather than inventing a third: ADR 4's lot-designation lock (once locked, later
corrections adjust basis only, never reopen the locked decision) and ADR 6's snapshot-vs-derivation
split itself. A restatement touching an already-charged period is recorded as a disclosed,
documented limitation to the customer — not resolved by a refund/reclaim subsystem, which is
explicitly out of scope for v1 (consistent with NFR-11's six-week timeline).

### Stripe events join the existing event-intake pipeline

Charge success/failure webhooks from Stripe Billing are ingested through the same idempotent
event-intake path (architecture.md, ADR 7's pattern) as every other external signal, keyed on
Stripe's event/charge ID — not a bespoke webhook handler with its own dedupe logic.

## Consequences

- S10 depends on S1 (ledger), S4 (TWR figures), and S6 (the publish watermark) existing first —
  reflected in the build order (`requirements.md`'s Sub-Project Decomposition: S10 follows S6).
- `fees_accrued_payable`, `fee_revenue_accrued`, and `fee_revenue_collected` extend S1's `account`
  `role` enum — consistent with how S1's own spec already flagged that enum as extensible (S5 adds
  `dividend_receivable`, `realized_gain_loss`; S10 adds these three).
- Every fee figure shown to a customer or exported must be explicit about whether it reflects a
  locked, already-charged period or a live, not-yet-charged accrual — the same labelling discipline
  ADR 6 already requires for return figures generally.
- A customer-facing disclosure is required wherever a restatement touches an already-charged fee
  period, since no automatic correction will occur (FR-47).

## Alternatives considered

- **Flat AUM-based fee** (a percentage of portfolio value, independent of gains). Simpler, and a
  legitimate alternative fee model generally, but does not match the brief's own wording
  ("performance fee") and forfeits the natural reuse of the already-decided TWR figure. Rejected in
  favor of a gains-based design that stays internally consistent with ADR 3.
- **No high-water-mark** (charge on any positive period gain, regardless of prior losses). Rejected:
  would charge the customer twice for the same economic gain across a drawdown-then-recovery cycle —
  the single most common objection to poorly-designed performance fees, and avoidable at low cost.
- **Charging directly against Alpaca cash** (deduct the fee from the investment account rather than
  a separate Stripe charge). Rejected: risks forcing a sell-to-cover when cash is insufficient,
  which would generate an unplanned taxable event (interacting with ADR 4's lot consumption and
  ADR 11's wash-sale detection) purely to pay a fee — a materially worse customer outcome than a
  separate, explicit payment-method charge.
- **Reopening and refunding a fee when its period is later restated.** More "correct" in the sense
  of always reflecting the true final number, but requires building a refund/reclaim subsystem
  against Stripe, a real-money reversal flow with its own failure modes, within a six-week timeline
  (NFR-11) — rejected for v1 in favor of a disclosed limitation, revisitable post-v1.
