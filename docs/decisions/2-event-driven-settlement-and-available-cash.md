# 2 — Settlement is event-driven; available cash is a computed policy

## Status

Accepted

## Context

FR-13 requires the T+1 settlement gap to be modeled explicitly: settled and available cash diverge
and reconverge, and unsettled proceeds cannot be withdrawn ("model the gap, do not hide it"). The
naive approach — treat `settlement_date` as the moment cash becomes settled — reports money as
settled the instant a calendar date rolls over, regardless of whether the custodian actually
confirmed the trade. That is fiction in the ledger, and it would let a customer withdraw money that
never settled.

## Decision

Settlement is represented as a state machine on an obligation, driven by external confirmation:

```
trade event → T+1 obligation created → settlement pending → custodian confirms → settlement event
```

- The transition to "settled" happens **only** on a custodian confirmation event.
- `settlement_date` is the *expected* date — a scheduling and risk input (when to expect
  confirmation, how late is this), never the trigger.
- There is **no physical movement of money** inside the ledger to represent settlement. No
  `cash:in_flight` → `cash:settled` transfer posting exists. Settlement changes the obligation's
  state, not the ledger.
- Available cash is not a stored balance or an account — it is a **computed policy/risk function**
  over settled state, open obligations, holds, and order commitments, evaluated on read (see
  ADR 5 for the two policies this produces).

## Consequences

- An obligation whose `settlement_date` has passed with no confirmation event *is* a reconciliation
  break, and its age is already computable — FR-31's aging requirement falls out of this model
  rather than needing separate tracking.
- FR-6 (a deposit that bounces after the cash was invested) is the `pending → failed` branch of the
  same state machine, not a special case requiring its own mechanism.
- Nothing in the system needs a nightly settlement-sweep job, and nothing can fail by that job not
  running.
- Every balance/available-cash query must join through obligation state rather than filtering a
  date column — slightly more query complexity than the date-only approach, accepted as the cost of
  correctness.

## Alternatives considered

- **`settlement_date`-driven queries** (`WHERE settlement_date <= today`). Rejected: reports
  unconfirmed cash as settled and available the moment the calendar date passes, independent of
  whether the custodian actually confirmed — directly contradicts "model the gap, do not hide it."
- **Explicit `cash:settled` / `cash:in_flight` accounts with a nightly settlement job** moving money
  between them. Rejected: there is no physical transfer of money to represent — settlement is a
  fact about an obligation, not a cash movement — and a scheduled job whose failure silently
  corrupts every balance is an unforced risk this design does not need.
