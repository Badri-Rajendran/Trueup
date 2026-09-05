# 12 — Market calendar source and timezone anchoring

## Status

Accepted

## Context

FR-40 requires distinguishing an expected non-trading day (a US market holiday) from an unexpected
missing/stale close (FR-15/NFR-6) — conflating the two would make S7's break-aging machinery
misfire every single holiday. NFR-13 separately requires every `effective_date` and daily-boundary
computation to be anchored to a single, explicit timezone. Both questions reduce to the same thing:
what does "a day" mean for a system whose every "daily," "morning," and "T+1" concept (valuation,
reconciliation, settlement) is fundamentally about US market days, not server clock days — and
neither was previously decided, gap findings #4 and #14.

## Decision

- **Timezone: America/New_York** anchors every `effective_date` and daily-boundary computation
  system-wide — daily valuation (S4), the morning reconciliation cutoff (S7), settlement-obligation
  expected dates (ADR 2), monthly rebalance scheduling (ADR 8), and daily fee accrual (ADR 10). This
  is the US market's own timezone (NYSE/Nasdaq); every "daily" concept in the brief is a market-day
  concept. `recorded_at` (ADR 1) is unaffected and stays a UTC `timestamptz` system-clock
  timestamp — it is not a market-day concept, only date-boundary logic converts through
  America/New_York.
- **Market calendar source: Alpaca's own trading-calendar API** (the same custody/data provider
  already in use, NFR-10's buy-not-build principle applied here too), not a hand-maintained holiday
  list. A day is only a genuine "missing close" (FR-15/NFR-6, a real anomaly) if the calendar marks
  it a trading day and no close arrived; a calendar-marked holiday or weekend is never flagged as a
  break.

## Consequences

- Every sub-project with "daily" logic (S4, S7, S9, S10) depends on one shared calendar service
  rather than each re-deriving its own holiday logic — a single point of truth, consistent with the
  architecture's core principle of deciding shared concerns once.
- A stored UTC instant near market close (4pm ET) must be converted through America/New_York before
  any day-boundary decision is made against it; getting this backwards silently reintroduces the
  exact off-by-one-day bug this ADR exists to prevent.

## Alternatives considered

- **UTC-anchored day boundaries.** Rejected: an entry recorded between 4pm ET market close and
  midnight UTC (a window that shifts with US daylight saving) risks landing on the wrong logical
  market day, corrupting exactly the bitemporal queries ADR 1 and ADR 6 depend on.
- **A hand-maintained holiday list.** Rejected: silently drifts stale (a missed manual update
  misclassifies a real holiday as a missing-close anomaly, false-alarming S7's break-aging exactly
  as gap finding #4 warned) where a provider-sourced calendar does not.
