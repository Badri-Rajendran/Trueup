# 6 — As-published snapshot at period close, cross-checked against derivation

## Status

Accepted

## Context

FR-26 requires the originally-published figure to "remain queryable forever." That requires a
precise definition of *publication* — if every screen view counted as a publication, storing a
snapshot per view would be absurd, and "as-published" would have no fixed meaning. Given ADR 1
(bitemporal ledger), as-published could instead be reconstructed purely by querying
`recorded_at <= T` for an arbitrary `T` — but that makes the published figure a reconstruction
rather than a recorded fact, and a latent ledger defect could then have the system confidently
reporting a historical figure it never actually showed anyone.

## Decision

- **Publication is a discrete event: period close / statement generation.** Ad-hoc screen views are
  always live, always as-corrected (`recorded_at <= now()`), and publish nothing.
- At publication, snapshot the return figure, balances, and holdings **immutably**, storing the
  figures **and the `recorded_at` watermark** at which they were computed.
- Independently, the same figures are always **derivable** from the ledger via ADR 1's
  bitemporal query, using the stored watermark.
- The two are cross-checked with a precise invariant:
  - `derive(period, recorded_at <= publish_watermark) == snapshot` — must hold **forever**.
  - `derive(period, now) != snapshot` is **expected** after a correction lands — that divergence
    *is* the restatement (FR-25), not a fault.

## Consequences

- The cross-check is not validating restatement arithmetic — it is a **tamper detector for the
  append-only ledger**. Under NFR-1, nothing should ever change what was true as of the publish
  watermark, so the first invariant can never fail. A failure means history was rewritten. This
  cross-check is NFR-1's actual enforcement mechanism, not a nice-to-have.
- Every consumer of "the published figure" must be explicit about which watermark it wants, or it
  will silently get the live, as-corrected figure instead — a labelling discipline that must be
  enforced at the query layer, not left to callers to remember.
- Snapshot storage grows with every period close, consistent with the append-only posture already
  accepted in ADR 1.

## Alternatives considered

- **Derive as-published from the ledger only, no snapshot.** Zero extra storage and perfectly
  consistent with the bitemporal model, but the published figure becomes purely a reconstruction —
  a ledger defect would report a historical number that was never actually shown to anyone, with no
  independent record to catch the discrepancy. Rejected for a regulated platform where "what did we
  tell the customer" must be a recorded fact.
- **Snapshot only, no cross-check.** Cheaper to build, but forfeits the tamper-detection property —
  the snapshot could silently drift from what the ledger says happened, with nothing to alert on it.
  Rejected given NFR-7 (return integrity is graded hardest).
