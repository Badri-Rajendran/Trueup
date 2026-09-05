# 4 — FIFO default with specific-lot override, closing at min(settlement, confirmation)

## Status

Accepted

## Context

FR-20 requires sells to consume tax lots under one declared, defended policy. A policy that selects
lots by cost (e.g. automated HIFO) interacts badly with restatement (ADR 1): if a corrected price
arrives for a lot, a cost-optimizing policy would retroactively change *which* lots should have been
sold — the correction would rewrite a past decision, not just adjust a number, in direct tension
with NFR-1.

Separately, U.S. tax law (Treas. Reg. §1.1012-1(c)) permits an investor to identify specific lots at
sale, no later than the trade's settlement date, with FIFO as the default absent adequate
identification — and expects broker written confirmation of the identification.

## Decision

- **Default: FIFO.** Oldest lot consumed first. Selection depends only on acquisition date, so a
  later price correction adjusts basis without ever changing which lots were consumed.
- **Override: specific-lot designation**, available to the investor no later than the applicable
  deadline (see below). An override is recorded as a **new designation event superseding the prior
  one** via `superseded_by` (ADR 1's machinery) — never an in-place edit.
- **Designation window closes at `min(settlement_date, confirmation event)`.** Bounded by the
  expected settlement date so a late-confirming custodian cannot silently extend the tax election
  window; also closed by confirmation itself, so a designation is never left mutable against lots
  the custodian has already relieved.
- Since the designation window spans from fill to deadline, **realized gain is provisional** during
  that window and must be labelled as such anywhere it is displayed or exported.
- The window is **per-fill, not per-order** — a partially filled order (FR-29) produces fills that
  settle on different dates, each opening and closing its own window.
- Once locked (by deadline or confirmation, whichever is first), later corrections adjust **basis
  only, never lot selection** — preserving NFR-1.
- The system self-issues the "broker written confirmation" the regulation expects, since Trueup
  owns lot accounting rather than the paper-trading broker. This is a documented limitation, not a
  regulatory workaround.

## Consequences

- FR-21 (realized/unrealized gains) and FR-22 (tax export) must both carry a provisional/final flag
  tied to the designation window, not just a lot-consumption result.
- UI copy for the deadline must read "on or before `<date>`", never "you have until `<date>`" — an
  early custodian confirmation closes the window sooner than the displayed expected date.
- Every rebalance-generated sell (S9, monthly, system-initiated) needs a defined default behavior
  for the override path even though no investor is present to designate lots for it: it uses FIFO,
  since no override was made.

## Alternatives considered

- **Specific-ID via automated cost optimization (HIFO).** Materially better tax outcomes, and what
  tax-aware robo-advisors typically run, but a corrected price can change which lot was "highest
  cost," making the correct selection shift retroactively — the exact restatement collision this
  design exists to avoid. Rejected for the default policy.
- **Specific-ID, investor elects on every sale, no FIFO default.** Rejected as the sole policy: most
  sells in this product are system-generated monthly rebalance trades with no investor present to
  elect lots at trade time, so a default is required regardless.
