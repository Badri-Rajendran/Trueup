# 3 — Time-weighted return methodology

## Status

Accepted

## Context

FR-16 requires one declared, defended return methodology. FR-17 requires that cash flows
(deposits/withdrawals) never pollute the reported return — "a deposit is not a return." The brief
names this the single most common domain failure it sees (line 48) and grades return integrity
under both flows and corrections as its hardest criterion (NFR-7). The methodology must also
compose with restatement (ADR 1): a corrected close for a single day must be able to update the
reported return without recomputing the customer's entire history from scratch.

## Decision

Returns are reported as **time-weighted return (TWR)**:

1. Break the reporting period into sub-periods at every external cash flow.
2. Compute each sub-period's return from daily closing valuations:
   `r_i = (V_end - V_begin - F_i) / V_begin`.
3. Link sub-period returns geometrically: `TWR = Π(1 + r_i) - 1`.

Because a flow always starts a new sub-period, it contributes exactly zero to the linked return by
construction, satisfying FR-17 structurally rather than by convention.

## Consequences

- A corrected close for a given day touches exactly one sub-period; only that sub-period's return
  is recomputed and the chain re-linked. Deterministic, unit-testable, and cheap — unlike money-
  weighted return (IRR), which requires numerically re-solving over the whole cash-flow history.
- TWR is the industry-standard (GIPS) methodology for reporting model-portfolio manager
  performance, which is the right frame here since the customer did not choose trade timing —
  the model portfolio and monthly rebalance did.
- TWR does not reflect the customer's own dollar-weighted experience (their personal timing of
  deposits/withdrawals). If a "how am I doing in dollars" figure is wanted alongside it, it must be
  built and labelled as a separate, explicitly non-return figure (net contributions / current value
  / dollar gain) — deferred to the S4 spec, not decided here.

## Alternatives considered

- **Money-weighted return (IRR).** Reflects the customer's actual dollar experience including their
  own flow timing, but flows move the figure by construction — in tension with FR-17 — and
  restating a single day requires re-solving the whole IRR numerically (Newton-Raphson), making
  as-published vs. as-corrected harder to prove deterministic. Rejected for the primary reported
  figure.
- **TWR as the official figure, dollar gain shown alongside, never labelled "return."** The
  stronger product answer, deferred rather than rejected — it is additive to this decision and can
  be layered into S4 without revisiting this ADR.
