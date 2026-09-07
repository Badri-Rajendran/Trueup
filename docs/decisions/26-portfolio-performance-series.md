# 26 — Portfolio performance series sourced from `sub_period_return`

## Status

Accepted

## Context

The Portfolio page redesign needs two pieces of new backend surface a customer has never had
direct access to before: what they actually hold (`GET /api/v1/portfolios/holdings`, distinct from
the model's *target* weights S8/S9 already expose) and a chartable performance history
(`GET /api/v1/portfolios/performance`). The holdings endpoint is a thin read model over
`DriftEvaluationService.evaluate()` (S9 §4) and needs no new architectural decision — it reuses an
existing, already-correct valuation path.

The performance endpoint does need one. FR-16/17 and S4 §5 (ADR 3) already compute time-weighted
return, but only two shapes of it exist today:

- `GET /api/v1/valuation/returns` — a single linked TWR figure for one caller-supplied
  `[period_start, period_end]` window, no series.
- `GET /api/v1/statements` — the **as-published** monthly `(period_start, period_end, twr,
  balance)` series (S6 §8, ADR 6). This is the authoritative "what did we tell the customer"
  record, immutable once published, and cross-checked for tamper detection.

Neither is what a Portfolio page chart needs: an as-of-now, live series of dated portfolio values
the customer can flip between `1m`/`3m`/`6m`/`1y`/`all`. `sub_period_return` (S4 §3.5) is the only
table in the system that stores a dated portfolio value at all (`value_begin`/`value_end` per
sub-period) — everything else is either a point-in-time computation over the ledger or the
as-published snapshot above. Its existing repository methods (`latest_for_sub_period`,
`as_of_for_sub_period`, `containing`) all resolve a single row for a known period; none returns an
ordered range.

## Decision

- **Source the live performance series from `sub_period_return`**, via a new
  `SubPeriodReturnRepository.list_in_range()` read — every latest-`recorded_at` row whose window
  overlaps the requested `[start_date, end_date]`, visible as of a `Watermark` (ADR 6's watermark
  discipline applied to a live read: `Watermark.live()`, never `datetime.now()` inlined in the
  service). `PortfolioPerformanceService` folds the ordered rows into `[{date, value}]` points
  (`value_begin` of the first row, then `value_end` of every row) and reuses
  `TwrService.link()` — the exact `product(1 + r_i) - 1` re-link `SnapshotService`'s restatement
  path already uses — to fold the same rows into one cumulative TWR, rather than re-deriving
  returns from the ledger a second time.
- **This is the live/as-of-now view.** `GET /api/v1/statements` remains the sole authoritative
  *published* series (ADR 6); the two are never merged or presented as interchangeable. The
  performance endpoint's figures can move on a later restatement (S6 §7) exactly the same way
  `GET /valuation/returns` already can; `GET /api/v1/statements` is what stays queryable unchanged.
- **`range` is a strict allowlist (`1m`/`3m`/`6m`/`1y`/`all`), never a free-form date pair.** A
  free-form `[start, end]` query would let a caller request an arbitrarily wide or oddly-anchored
  window, which is both an unbounded-query risk (NFR-class concern the rest of this codebase treats
  seriously — cf. every other list endpoint's pagination/limit discipline) and uncacheable, since
  the response shape depends on wall-clock "now" for every distinct pair a client could construct.
  A fixed enum keeps the response cacheable per-customer-per-range and keeps the query bounded.
- The service method takes `range` as a required keyword argument, no default (mirroring
  `as_of: Watermark`'s no-default convention, ADR 6/14) — a caller cannot silently get "some"
  range. The controller alone may default the query parameter (e.g. `1m`) before calling the
  service, matching how every other date-boundary read in this codebase pushes the "what does
  'no input' mean" decision to the edge, not into the service.
- The series reflects whatever `sub_period_return` coverage already exists for that customer
  (populated by `GET /valuation/returns`, statement publication, restatement, and fee accrual's
  high-water-mark computation — S4 §5, S6, S10). The endpoint is a pure read: it never triggers a
  fresh `TwrService.compute_twr()` write path itself. A customer with no covered sub-periods in the
  requested range gets an empty `points` series and a zero cumulative TWR — the same "legitimately
  nothing here yet" shape `ValuationService`/`DriftEvaluationService` already use for an
  unfunded account, not an error.

## Consequences

- No new table, no Alembic migration — `sub_period_return` already carries everything the series
  needs.
- The performance series' completeness is bounded by which periods some other flow has already
  caused to be computed and stored; it is not guaranteed to be a dense, gap-free daily series. This
  is an explicit trade-off (see alternatives below), not an oversight, and is safe precisely because
  every consumer of "the published figure" already has its own, independently-derived source of
  truth (`GET /api/v1/statements`) that this endpoint never substitutes for.
- `list_in_range()` follows the same latest-`recorded_at`-per-window dedupe `containing()` already
  established, so a restated sub-period is picked up automatically without any change to this
  endpoint.

## Alternatives considered

- **Have the performance endpoint call `TwrService.compute_twr()` itself for the requested range,
  materializing any missing sub-periods on the fly.** Would guarantee a dense series, but turns a
  plain "view your performance" `GET` into a request that reads the whole ledger and writes new
  `sub_period_return` rows as a side effect of a read — a surprising, harder-to-reason-about
  contract, and redundant with the read paths (`GET /valuation/returns`, statement publication,
  fee accrual) that already populate this table as their own side effect. Rejected in favor of a
  pure read; can be revisited if product data shows real gaps once this ships.
- **Derive the series live from the ledger** (`ValuationService.value_book()` per day in range),
  bypassing `sub_period_return` entirely. Avoids the coverage gap above, but re-derives TWR-relevant
  figures the codebase already has a canonical, restatement-composable way to produce
  (`TwrService.link()`), and turns a chart endpoint into an O(days) ledger scan. Rejected — exactly
  the kind of duplicated derivation ADR 3/S4 §5 exists to avoid.
- **Accept a free-form `[start, end]` query parameter pair instead of an enum.** More flexible for
  a future custom-range chart control, but unbounded (a caller could request decades of history)
  and uncacheable per the reasoning above. Rejected for v1; a future ADR can widen this if the
  product need materializes, the same way `GET /valuation/returns` already accepts explicit dates
  for its single-window use case.
