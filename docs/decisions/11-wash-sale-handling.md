# 11 — Wash sale detection and basis adjustment

## Status

Accepted

## Context

FR-37 requires detecting and handling wash sales. This is not an edge case for Trueup: monthly
automated rebalancing (ADR 8) routinely sells a losing position back toward target weight and, in a
later month, buys it again as drift or a fresh deposit calls for it — the textbook shape of a wash
sale (IRS: a loss sale followed by acquiring the same or a "substantially identical" security within
the 61-day window spanning 30 days before through 30 days after the sale). Left undetected, FR-21
(realized/unrealized gains) and FR-22 (the tax export) would report disallowed losses as real ones —
exactly the kind of tax-lot defect the brief grades hardest (line 77), and gap finding #1.

## Decision

- **Detection scope: same-security (same CUSIP) repurchases only for v1.** Trueup's four model
  portfolios hold a fixed, known set of securities, so same-security matching covers the case this
  product actually produces. Matching against IRS's broader "substantially identical" securities
  (e.g. different share classes) is a genuinely unsettled area of tax law even for professionals and
  is out of scope for v1 — documented as a limitation, not silently ignored.
- **Mechanism reuses the existing ledger primitives, adds no new machinery.** A detected wash sale
  posts a `wash_sale_adjustment` journal entry (ADR 1) with two money legs that sum to zero (S1's
  invariant): `realized_gain_loss` is credited by the disallowed loss amount (reversing the loss
  that was about to be recognized), and the **replacement lot's** `position_cost` account is debited
  by the same amount (the disallowed loss is not lost — it is carried into the replacement lot's
  basis, per the IRS rule). This is an append-only adjustment entry, not a correction of a mistake,
  so it does not use `superseded_by` — it is a new fact discovered once the replacement buy occurs.
- **Lot selection is unaffected.** The wash sale rule adjusts *basis*, exactly like ADR 4's
  restatement-safe design already requires — it never changes which lots were consumed by the
  original sale.
- **Window spans month and restatement boundaries without special-casing.** Because the adjustment
  is just another append-only entry, a wash sale discovered after a period has already closed (the
  replacement buy lands in the following month) or after a restatement has touched the original
  sale composes cleanly with ADR 1's and ADR 6's existing machinery — no new temporal reasoning
  required.

## Consequences

- FR-21 (realized/unrealized gains) and FR-22 (the tax export) must read post-wash-sale-adjustment
  state, not the raw sell entry — a query that ignores `wash_sale_adjustment` entries will overstate
  realized losses.
- The replacement lot's basis is no longer purely "acquisition price" — it must reflect any
  wash-sale-carried disallowed loss, which S5's lot model must expose distinctly (e.g. an
  `adjusted_basis` alongside the original purchase cost) so the carry is auditable, not opaque.

## Alternatives considered

- **No wash-sale handling.** Rejected: the brief grades tax lots as one of the hardest areas, and
  monthly rebalancing makes wash sales routine rather than rare — silently misreporting disallowed
  losses as real ones is a direct tax-accuracy defect, not a corner case that can be waved away.
- **Matching across broader "substantially identical" securities.** Rejected for v1: genuinely
  unsettled even in professional tax practice, and unnecessary given the four model portfolios'
  fixed, known holdings make same-CUSIP matching sufficient to cover the cases this product actually
  generates.
- **Disallow the loss without carrying it into the replacement basis** (i.e. simply not counting the
  loss at all). Rejected: misstates the customer's true economic position — the IRS rule defers the
  loss, it does not forfeit it, and permanently discarding it would understate the customer's basis
  and overstate a later gain when the replacement lot is eventually sold.
