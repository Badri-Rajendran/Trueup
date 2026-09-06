# NN3 (the correction test) and automatic-fail #3 (money-row immutability)

**Status:** Draft, pending review.

## Context

A compliance audit against `docs/requirements/non-negotiables.md` and
`docs/project-rubrics/scoring.md`, run by three parallel agents against real code (not
documentation claims), confirmed two FAIL-level findings:

- **NN3, the correction test** — explicitly demoed live in the debrief. `PostingService.correct()`
  (the reversal+re-book mechanism) has zero production callers; the one test that exercises it
  doesn't construct a genuine reversal (would double-count under the ledger's own additive-sum
  balance model); and nothing republishes a statement snapshot after a restatement, so
  `GET /statements/<period>` would keep serving the stale pre-correction figure indefinitely.
- **Automatic-fail #3** — "UPDATE or DELETE on money rows. Anywhere. Ever." Six tables beyond the
  core `journal_entry`/`posting` ledger permit `UPDATE` at the DB grant level and are actively
  mutated by service code: `order`, `tax_lot`, `lot_consumption`, `high_water_mark`, `fee_charge`,
  `approval_hold`.

The user directed implementing only these two FAIL items (not the PARTIAL findings — bitemporal
read reach, webhook atomicity, the MCP approval UI, decision-log currency — which stay out of
scope), in one pass covering all six tables, with `settlement_obligation` explicitly left
unverified/out of scope per the user's own choice.

This document is the design for both. Both problems turn out to share real architecture already
in this codebase — `order`'s own docstring documents it as "the rebuildable projection (ADR 7)...
`assert projection == fold(order_event)` holds," with `order_event` already correctly
append-only. The gap is that `order` itself was never given `REVOKE UPDATE` to match, and the
same "append-only facts, derived projection" shape is the house style this design replicates
across the other five tables. Likewise, NN3's real mechanism already exists —
`CustodianFileAdapter.inject_corrected_price()` (S7 §9) already posts a corrected `daily_close`
and fans `RestatementService.restate()` out to every affected customer — it just never republishes
a snapshot afterward, which is the one missing step.

---

## Part 1 — NN3: the correction test

### 1.1 What already works, verified by reading the actual code

- `PostingService.post()`/`correct()` (`backend/app/services/ledger/posting_service.py`) — real,
  DB-backed, zero-sum-validated journal-entry writer. `correct()` sets `superseded_by` on a new
  entry pointing back at the one it corrects; the original row is genuinely never mutated
  (confirmed: `journal_entry.superseded_by` docstring, `REVOKE UPDATE, DELETE` on both
  `journal_entry` and `posting`).
- `RestatementService.restate()` (`backend/app/services/restatement/restatement_service.py`) —
  already wired to four real trigger types (`RestatementTriggerType`:
  `CORRECTED_CLOSE`, `LATE_DIVIDEND`, `SPLIT`, `WASH_SALE_ADJUSTMENT`, plus an unused
  `MANUAL_CORRECTION`). Three call sites already exist:
  `custodian_file_adapter.py:134` (a corrected closing price — this is almost certainly the
  literal "a corrected price restates the affected period's return" scenario named in
  `docs/requirements/project-description.md`), `wash_sale_service.py:137`, and
  `corporate_action_service.py` (late dividend, split — two call sites).
- `restate()` recomputes the live `sub_period_return` rows for every window touching the affected
  date, then `_relink_and_cross_check()` re-links the live TWR for any already-published period
  that overlaps and calls `SnapshotService.cross_check()` on it — proving the *old* snapshot still
  reproduces exactly at its *own* `publish_watermark`. This is deliberate tamper-detection (ADR
  6), not a "keep it fresh" mechanism: a published snapshot is meant to be permanently frozen, and
  cross-check alarms loudly (`SnapshotCrossCheckFailedError`) if history was ever rewritten under
  it. **This part must not change** — it is exactly what "the as-published figure stays queryable"
  requires.

### 1.2 The actual gap

`_relink_and_cross_check` proves the old snapshot is still valid and stops there — it never
creates a *new* snapshot reflecting the correction. `GET /statements/<period_start>`
(`backend/app/controllers/api/statements.py`) reads `published_snapshots.latest_for_period()` — a
frozen, stored row. Since nothing ever inserts a second `published_snapshot` row for an
already-published period, that endpoint keeps returning the pre-correction figure forever, even
though the live `/valuation/returns`/`/valuation/balance` endpoints (which recompute rather than
read a cached snapshot) already correctly reflect the correction on their next call.

This is precisely the gap the frontend was already built for and is waiting on: the earlier
session's design-doc audit found `StatementList.jsx`/`StatementDetail.jsx` already implement the
"Restated" badge, the struck-through original figure, and a "View original as-published statement"
link (design-system.md §8.1) — unreachable today only because the backend condition it depends on
(`versions.length > 1`, i.e. a second `published_snapshot` row existing for the period) can never
become true.

### 1.3 Fix — republish after a correction

In `RestatementService._relink_and_cross_check`, after `snapshot_service.cross_check(snapshot)`
passes for a touched, already-published period, call `snapshot_service.publish(customer_id,
snapshot.period_start, snapshot.period_end)`. This creates a **new** `published_snapshot` row with
a new `publish_watermark` (Postgres's own transaction-start `now()`, per `publish()`'s existing
contract) holding the corrected figures. `PublishedSnapshotRepository.latest_for_period()` then
naturally returns the newest snapshot going forward; the original stays independently fetchable
forever via its own `publish_watermark` (the existing `?publish_watermark=` query param on
`GET /statements/<period>`, already wired end-to-end).

Guard against redundant snapshots: only publish again if the derived figures actually differ from
the existing latest snapshot's `twr`/`balance` (compare `SnapshotService.derive()`'s live figures,
already computed for the cross-check, against the current latest snapshot) — a restatement whose
recomputation produces no real change (e.g. `compute_twr`'s reuse-or-recompute path returning
identical numbers) should not manufacture a spurious new "restated" version. This one condition is
the only new logic beyond an additional `publish()` call.

This single fix applies uniformly to all four trigger types — no per-trigger special-casing needed.

### 1.4 Fix — make `correct()` itself actually correct, and give it a real caller

The one existing test (`backend/tests/integration/test_ledger_append_only.py`) exercises
`correct()` with legs that re-book the new total (`+900/-900`) without reversing the original
(`+1000/-1000`). Since every real balance path (`ValuationService`, `SnapshotService`,
reconciliation) sums **all** postings unconditionally with no `superseded_by` filtering, by
design, a correction that doesn't include true reversal legs double-counts. Fix the test (and, if
`correct()`'s signature makes it easy to get wrong, consider having `correct()` itself compute and
post the negated original legs automatically alongside the caller's new legs, so a caller
physically cannot construct a non-reversing correction) — this makes the capability genuinely
correct regardless of whether it ever gets a production caller.

Separately, give it one: `RestatementTriggerType.MANUAL_CORRECTION` already exists in the enum and
is unused — the scaffolding anticipates exactly this case (a staff member correcting an
erroneously-posted journal entry, as opposed to a late dividend/split/price-correction, which are
all legitimately handled by *posting a new entry*, not correcting an old one — those three don't
need `correct()` at all, and shouldn't be forced to use it). Add one minimal admin-facing service
method (e.g. on a new or existing admin service) taking `(original_journal_entry_id, new_legs,
reason)`, calling `PostingService.correct()` and then `RestatementService.restate(...,
trigger_type=MANUAL_CORRECTION)`. A full API route + frontend UI for this is out of scope unless
requested — the requirement is that the capability exists and is correct and reachable, not that
staff have a polished screen for the rare case of a genuine posting error.

### 1.5 Fix — `curated_views.py`'s inverted filter

`app/models/chat/curated_views.py` filters `WHERE je.superseded_by IS NULL` in three views. Given
the confirmed field semantics (`superseded_by` is set on the *new* correcting entry, pointing back;
the original's own `superseded_by` stays null forever), this filter *keeps* the stale original and
*excludes* the correction — backwards, and inconsistent with `ValuationService`'s own documented
"sum everything unconditionally, no `superseded_by` special-casing" model. Remove the filter
entirely to match, rather than inverting it (inverting would still be special-casing something the
rest of the codebase deliberately doesn't).

### 1.6 Tests to add

- `test_snapshot_service.py` — `publish()`, `derive()`, `cross_check()` in isolation, including the
  "derive at an old watermark still reproduces the original" case and the "cross-check fails loudly
  on genuine tampering" case.
- `test_restatement_service.py` — `restate()` end-to-end, including the new republish behavior and
  its no-redundant-snapshot guard.
- One true end-to-end scenario test mirroring the literal demo: inject a corrected close price for
  a security a customer holds and a date inside an already-published period → assert
  `GET /statements/<period>` (no watermark) now returns the corrected balance/TWR, and
  `GET /statements/<period>?publish_watermark=<original>` still returns the untouched original,
  and reconciliation still balances.
- A `correct()` unit test with genuine reversal legs, asserting the summed balance nets to the
  corrected value, not the sum of both postings.
- A test for the new manual-correction entry point.

---

## Part 2 — automatic-fail #3: money-row immutability

### 2.1 The pattern, established by precedent already in this codebase

`order` / `order_event` (ADR 7) is the house style: an append-only table of facts
(`order_event`, already `REVOKE UPDATE, DELETE`'d) plus a **derived** read — the model docstring's
own words, "the rebuildable projection... `assert projection == fold(order_event)`." The fix for
all six tables is the same shape: stop writing money/unit columns in place after creation; either
derive them at read time by folding an append-only event/adjustment log, or replace a single
mutable row with an append-only history and read the latest/aggregate. Then `REVOKE UPDATE` for
real.

### 2.2 Table by table

**`order`** (`quantity_requested`, `filled_quantity`, `average_fill_price`) — closest to done
already; `order_event` exists and is correctly append-only. Two write sites currently mutate
`order` directly: `order_projection_service.py:95-97` (folds `order_event` into the cached
columns — this is the one to eliminate, replacing every direct read of
`order.status`/`filled_quantity`/`average_fill_price` with a call to a new pure
`derive_order_state(events: Sequence[OrderEvent]) -> OrderState`-style function, called at read
time instead of cached at write time) and `order_service.py:136` (`order.status =
OrderStatus.APPROVED` — a genuine pre-submission transition with no corresponding event type
today). Resolution: extend `OrderEventType` to cover the pre-submission approval transition too
(e.g. `APPROVAL_REQUESTED`/`APPROVED`), so `order.status` is derived from folding events across its
*entire* lifecycle, not just from `submitted` onward as today — not the alternative of treating
`approval_hold` as the source, since not every order has a hold (only those crossing the
auto-approval threshold), so it can't universally answer "is this order approved" for orders that
skip that step entirely. This keeps one derivation rule for the whole table instead of a
pre-/post-submission split. Currently has
**zero** grant restriction at all (worse than the other five) — add `REVOKE UPDATE, DELETE` in the
same migration pass regardless of which sub-approach is chosen for the approval transition.

**`tax_lot`** (`quantity_remaining`, `adjusted_basis`) — `quantity_remaining` derives cleanly as
`original_quantity − SUM(lot_consumption.quantity_consumed)` for the lot, no new table needed.
`adjusted_basis` needs a new append-only `tax_lot_basis_adjustment` table (lot_id, delta, reason,
source_event_id), written by `wash_sale_service.py`/`corporate_action_service.py` instead of
mutating `tax_lot.adjusted_basis` directly; derived as `original_cost_basis + SUM(deltas)`.
`REVOKE UPDATE`.

**`lot_consumption.realized_gain_loss`** — mutated by `wash_sale_service.py:132`'s disallowed-loss
adjustment. Shares its root cause with Part 1: once wash-sale correctly posts a **ledger**
correction (§1.4) for the disallowed amount instead of mutating this column, `realized_gain_loss`
becomes a derived read (original recognized amount + any linked correcting postings) rather than a
stored mutable value. One fix serves both problems. `REVOKE UPDATE`.

**`high_water_mark.peak_value`** — the model's own docstring calls this "the one intentional
exception to append-only." Convert from a single mutable row per account to an append-only history
(a new row per ratchet update, never mutating an existing one); current peak = `MAX(peak_value)`
or the latest row by timestamp for that account. This is the simplest of the six. `REVOKE UPDATE`.

**`fee_charge`** (`status`, `stripe_charge_id`, `journal_entry_id` mutated in
`fee_charge_service.py`/`dunning_service.py`) — new append-only `fee_charge_event` table (same
shape as `order_event`) recording each lifecycle transition as a new row; current `status`/
`stripe_charge_id` derived from the latest event for that charge. `REVOKE UPDATE`.

**`approval_hold`** (`status`, `released_at`, `release_reason` mutated in
`approval_hold_service.py:46-48`) — same event-log treatment as `fee_charge`. (This codebase has a
precedent for a *constrained* single-transition-trigger `UPDATE` instead —
`settlement_obligation`/`agent_action_request` — deliberately not used here: the rubric's "anywhere,
ever" has no carve-out for a constrained update, so `approval_hold` gets the full append-only
treatment like the rest, not the trigger pattern.)

### 2.3 Migrations

One migration per table (or one combined migration touching all six, matching this project's
existing style of one focused migration per logical change — follow whichever convention recent
migrations in `backend/alembic/versions/` establish): the new event/adjustment tables where
needed, `REVOKE UPDATE, DELETE` (or `REVOKE UPDATE` where `DELETE` is already revoked) on all six
existing tables, and — for `order` specifically — closing the currently-wide-open grant.

### 2.4 Read-site sweep

Every place that currently reads a column being converted to derived (`order.status`,
`order.filled_quantity`, `order.average_fill_price`, `tax_lot.quantity_remaining`,
`tax_lot.adjusted_basis`, `lot_consumption.realized_gain_loss`, `high_water_mark.peak_value`,
`fee_charge.status`, `fee_charge.stripe_charge_id`, `approval_hold.status`) needs to switch to the
new derivation function instead. This is the largest mechanical surface of the whole change —
enumerate every call site per table during implementation (grep the exact column name), not
assumed complete by this list.

### 2.5 Tests to add/update

Per table: a test proving the DB grant genuinely rejects `UPDATE` under the app role (matching the
existing pattern in `test_ledger_append_only.py`), and a test proving the derivation function
produces the correct current state from a sequence of events/adjustments, including out-of-order
event arrival where that's already handled for `order_event` (`seq` is independent of processing
order, per its own docstring) and needs to hold for the new event tables too. Every existing test
that currently asserts against a mutated column (e.g. `order.filled_quantity == X` after a fill)
needs updating to assert against the derived read instead — full inventory during implementation.

---

## Scope boundaries (explicit)

**In scope:** exactly the two FAIL findings above, across all six flagged tables plus the
correction/republish mechanism, in one implementation pass.

**Out of scope, by the user's own direction:**
- `settlement_obligation` — not verified against automatic-fail #3 by the audit; left
  unverified rather than assumed.
- Every PARTIAL finding from the same audit: bitemporal read reach beyond published periods,
  webhook atomicity/out-of-order handling, the MCP frontend approval UI, decision-log currency,
  CD pipeline secrets, Alpaca going fully live. None of these are touched here.
- A full API route + frontend UI for the manual-correction entry point (§1.4) — the capability
  must exist and be correct and reachable; a polished staff screen for it is not required by
  either failing item.

## Verification

- `uv run pytest` (full backend suite) green, including every new/updated test above.
- `uv run ruff check` / `uv run mypy --strict app` / `uv run lint-imports` clean.
- A manual run of the literal NN3 scenario end-to-end: inject a corrected price for an
  already-published period, confirm the statement endpoint shows the corrected figure while the
  as-published watermark still returns the original, and reconciliation still balances.
- For automatic-fail #3: a direct grant check per table (`\dp` or an information_schema query)
  confirming zero UPDATE/DELETE privilege for `trueup_app`/`trueup_worker` on all six tables, plus
  a live attempt to `UPDATE` each one under the app role and confirm it's rejected.
