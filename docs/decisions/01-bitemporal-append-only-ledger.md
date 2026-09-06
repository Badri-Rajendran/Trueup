# 1 — Bitemporal, append-only ledger

## Status

Accepted

## Context

NFR-1 requires that ledger entries are immutable and history is never rewritten. FR-25/FR-26
require that when a late correction (dividend, split, corrected close) affects an already-reported
period, the affected return is restated — and *both* the originally-published and the corrected
figures remain independently queryable forever. A naive ledger that `UPDATE`s a balance in place
cannot satisfy either requirement: there would be nothing left to query for "what we told the
customer then."

## Decision

Every posting carries two timestamps:
- `effective_date` — when the economic event happened (trade date, ex-date, etc.).
- `recorded_at` — when the system learned of it.

Corrections are new postings, never edits. A superseding posting links back to the one it corrects
via `superseded_by`. Nothing in the ledger is ever `UPDATE`d or deleted.

This makes both temporal views a query, not a rebuild:
- **As-published** for a period `P` as of time `T`: `WHERE recorded_at <= T`.
- **As-corrected** (current truth) for `P`: `WHERE recorded_at <= now()`.

## Consequences

- Restatement (S6) becomes a `WHERE` clause difference, not a schema migration or a rebuild —
  deterministic and unit-testable.
- Storage grows monotonically; corrections add rows rather than shrinking history. Accepted, since
  the brief treats this as the regulatory floor, not an optimization target.
- Every read path that reports a figure must be explicit about which watermark it is querying
  against — an easy mistake to leave implicit. Mitigated by ADR 6's snapshot-plus-cross-check.

## Alternatives considered

- **Naive ledger + rebuild on correction.** Rejected: violates NFR-1 directly (history is rewritten
  in place), and would require S6 to be built as a schema migration against the system's most
  critical table after other sub-projects are already reading from it.
- **Event-sourced ledger** (domain events as sole source of truth, postings as a rebuildable
  projection, restatement as replay). Considered and rejected for v1: most faithful to "never
  rewrite history," but the heavier machinery (replay determinism, projection versioning, rebuild
  tooling) does not fit a six-week timeline (NFR-11). The bitemporal posting model gets the same
  guarantee with two columns and a correction chain.
