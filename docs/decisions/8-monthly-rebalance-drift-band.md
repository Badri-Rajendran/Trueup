# 8 — Monthly rebalance, drift-band gated

## Status

Accepted

## Context

The brief states the cadence directly, not as a choice: "we rebalance monthly" (line 7), captured
as FR-27. FR-28 separately requires order generation to account for drift from model weights,
order minimums, fractional-share rules, and a cash buffer — which implies trades are not generated
unconditionally every month regardless of how small the drift is. Continuous (e.g. daily) drift
monitoring was evaluated during design and found to conflict with FR-27 as written; the accepted
decision below resolves that conflict without deviating from the requirement.

## Decision

- **The calendar decides when to check**: drift from model target weights is evaluated on a
  monthly schedule, satisfying FR-27 directly.
- **A tolerance band decides whether to trade**: a holding within its band at the monthly check is
  left alone; only holdings outside the band generate rebalance orders.
- Band width and whether it is absolute or relative to target weight are parameters to be chosen
  and defended in the S9 spec, not decided here.

## Consequences

- Fewer trades than an unconditional monthly rebalance-to-exact-target, which means fewer realized
  gains (relevant under ADR 4's FIFO/specific-ID lot consumption and FR-21) and lower fees for
  drift that is already negligible.
- Accepted trade-off: drift between month-end checks is not corrected. A sharp mid-month market
  move waits for the next scheduled run. This is consistent with the brief's stated cadence and is
  not treated as a defect.
- No daily job is required to operate or monitor for this purpose.

## Alternatives considered

- **Monthly, unconditional rebalance to exact target weight.** Simplest rule and fully predictable,
  but realizes taxable gains and pays fees every month even for trivial drift, and churns tax lots
  (ADR 4) on a fixed monthly cycle regardless of whether it is warranted. Rejected in favor of
  band-gating, which the brief's mention of "drift from model weights" (line 50) implies is the
  intended shape.
- **Continuous (e.g. daily) drift monitoring, trading whenever a holding leaves its band.**
  Tightest tracking to the model and fastest response to market moves, but **directly contradicts
  FR-27 / brief line 7**, which states the cadence as monthly rather than delegating it as a
  choice. Also multiplies downstream cost: roughly 30× the drift evaluations, more lots opened and
  consumed, more realized gains, more settlement obligations in flight simultaneously (ADR 2),
  a larger free-riding surface to track (ADR 5), and more concurrently open lot-designation
  windows (ADR 4). Rejected — adopting it would have required recording a deviation from an
  explicit requirement and updating `docs/requirements/requirements.md` to match, which was not
  warranted here.
