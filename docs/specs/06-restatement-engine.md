# S6 — Restatement Engine: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-25–26
Depends on: S4 (`sub_period_return` rows, per-sub-period recomputation), S5 (a corrected cost basis
or wash-sale adjustment is also a restatement input, not only a price correction)
Consumed by: S10 (the fee-lock mechanism reads this spec's publish watermark and explicitly does not
reopen a charged fee when a later restatement lands), S8 (statements/exports must label live vs.
as-published, per this spec's own discipline), S11 (the chat assistant's as-published answers query
this spec's `published_snapshot` directly)

## 1. Purpose

The brief's own words: "we run this live." A late-arriving correction restates the affected period's
return to the correct value; the originally-published figure remains queryable forever; both are
first-class (FR-25–26). ADR 6 already decided the *shape* of this (publish is a discrete event, a
snapshot plus a derivation cross-check); this spec is what actually triggers a restatement, what gets
recomputed, and how `SnapshotService` implements the cross-check as a concrete, runnable check rather
than a stated invariant.

## 2. Non-goals

- What counts as a correction event (a corrected close, a late dividend, a wash-sale adjustment) —
  those are S4/S5's own posting mechanisms; this spec reacts to them, it does not produce them.
- The TWR sub-period algorithm itself — S4; this spec calls it, it doesn't reimplement it.

## 3. Schema

### 3.1 `published_snapshot` (ADR 6)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `period_start`, `period_end` | date | |
| `publish_watermark` | timestamptz | the `recorded_at` cutoff this snapshot is pinned to (ADR 1/6) |
| `twr` | numeric | the linked return as of the watermark |
| `balance` | `Money` | |
| `holdings_json` | jsonb | a point-in-time holdings snapshot, sufficient to reconstruct what was shown |
| `published_at` | timestamptz | when publication happened (period close / statement generation) — distinct from `publish_watermark`, which is the ledger cutoff, not the wall-clock moment of publication |

No `UPDATE`/`DELETE` grant — same append-only posture as `journal_entry` (NFR-1 extended to
published figures, not only ledger postings).

### 3.2 `restatement_event`

The audit trail of *why* a given period was recomputed — not required for correctness (the
recomputation itself is what matters), but required so a customer dispute or an adviser question
("why did my March return change?") has a concrete, queryable answer rather than an inference from
timestamps alone.

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `affected_period_start`, `affected_period_end` | date | |
| `trigger_type` | enum | `corrected_close` \| `late_dividend` \| `split` \| `wash_sale_adjustment` \| `manual_correction` |
| `trigger_source_event_id` | uuid, FK → the `inbound_event`/journal entry that caused this | |
| `recomputed_at` | timestamptz | |

## 4. What triggers a restatement

`RestatementService` subscribes to the same event categories S4/S5 already post through S1's
intake path — it adds no second listening mechanism, it is a reaction registered against entries of
`entry_type IN (correction, dividend, split, wash_sale_adjustment)` or a new `daily_close` row with
`status = 'confirmed'` superseding an earlier `stale`/differently-valued confirmed row for the same
`market_date`. Concretely:

```
on_new_correcting_entry(entry):
    affected_date = entry.effective_date   # the date whose economic truth just changed
    affected_period = the reporting period(s) whose sub-periods span affected_date
                       (per S4's stored per-sub-period rows — usually exactly one)
    RestatementService.restate(customer_id, affected_period, trigger_type, entry.source_event_id)
```

## 5. Recomputation pipeline

```
restate(customer_id, period, trigger_type, source_event_id):
    1. log a restatement_event row (§3.2) — the "why" record, written before recomputation starts
    2. recompute exactly the sub_period_return row(s) whose [v_begin, v_end] window contains
       affected_date (S4 §5's stored-per-sub-period design is what makes this "exactly one row"
       rather than "the whole period", per ADR 3's claimed and now literal property)
    3. re-link the period's TWR: product(1 + r_i) - 1 over the (now partially updated) stored
       sub-period rows — a re-link over existing numbers, not a re-derivation from raw postings
    4. the LIVE figure (queried with as_of = now()) now reflects the correction immediately;
       nothing is snapshotted by this step alone — see §6 for when publication happens
```

**This is deliberately cheap and deterministic** — recomputation touches one stored row and relinks,
never a full re-derivation of the customer's history, which is the concrete payoff ADR 1/3 designed
for and this spec is what actually delivers it.

## 6. Publication and the cross-check (ADR 6, made concrete)

`SnapshotService.publish(customer_id, period)`:

```
publish(customer_id, period):
    watermark = now()   # recorded_at cutoff, fixed at the instant of publication
    figures = derive(customer_id, period, recorded_at <= watermark)   # S4's live computation,
                                                                        # pinned to this watermark
    insert published_snapshot(period, publish_watermark=watermark, twr=figures.twr, ...)
```

`SnapshotService.cross_check(snapshot)` — **the actual, runnable form of ADR 6's invariant**, not
just a stated property:

```
cross_check(snapshot):
    rederived = derive(snapshot.customer_id, snapshot.period, recorded_at <= snapshot.publish_watermark)
    assert rederived.twr == snapshot.twr and rederived.balance == snapshot.balance
    # must hold FOREVER, run continuously (e.g. as part of every restatement, and on a periodic
    # sweep independent of any restatement) — a failure here means history was rewritten (ADR 6),
    # which is a tamper/corruption alert, not a business-logic bug to quietly fix
```

`cross_check` is invoked automatically after every `restate()` call (§5) for every **already-
published** period the restatement touched — the live figure is expected to now differ from the
snapshot (that divergence *is* the restatement, FR-25), but re-deriving *at the old watermark* must
still match the old snapshot exactly, proving the correction didn't somehow also rewrite what was
already published. `cross_check` is additionally run on a periodic sweep over all snapshots,
independent of restatement activity, as a standing tamper-detection job (ADR 6's stated purpose).

## 7. As-published vs. live, surfaced correctly

Every read path returns a `watermark_type: 'live' | 'as_published'` alongside any period-specific
figure (FR-52/S11 already require this at the chat layer; this spec is where the underlying
capability actually lives, for S8/S11 to both consume identically):

```
get_return(customer_id, period, as_of='live' | a specific publish_watermark):
    if as_of == 'live': return S4.derive(customer_id, period, recorded_at <= now()), watermark_type='live'
    else: return the published_snapshot matching that watermark, watermark_type='as_published'
```

A caller that wants "what did you originally tell me" passes the specific `published_snapshot`'s
watermark, obtained via `GET /api/v1/statements` (§8) — never a raw timestamp typed by a caller,
since an arbitrary timestamp that doesn't correspond to an actual publication event would produce a
number nobody was ever shown, defeating the entire point of "as-published."

## 8. API contract

- `GET /api/v1/statements` → list of published periods for a customer, each with its
  `publish_watermark` (the handle §7 requires for an as-published query).
- `GET /api/v1/statements/<period>` → the published snapshot's figures.
- No customer-facing "trigger a restatement" endpoint — restatement is always system-triggered by a
  correcting entry (§4), never a manual customer action.

## 9. Edge and corner cases

1. **Two corrections landing for the same period in quick succession** (e.g. a corrected close, then
   a late dividend for the same month) — `restate()` runs twice, each recomputing whatever
   sub-period(s) it individually affects; the second run's `cross_check` against the *original*
   snapshot still passes (the snapshot is unaffected by either), and the live figure now reflects
   both corrections cumulatively, correctly, since each recomputation only ever adjusted its own
   stored sub-period row.
2. **A correction affecting a period that has never been published** — recomputation still happens
   (§5), but there is no snapshot to cross-check against; `restatement_event` is still logged for
   audit purposes even though FR-26's "both queryable forever" guarantee only applies once a period
   has actually been published at least once.
3. **A correction arriving for a period so old its `sub_period_return` rows have been re-derived
   many times** — no special handling needed; the stored-row-plus-relink design (§5) doesn't
   accumulate complexity with the number of prior corrections, since each recomputation only ever
   touches the specific row the new correction's `affected_date` falls into.
4. **`cross_check` failing** — this is the tamper-detection alarm ADR 6 names explicitly; the
   correct system behavior is a loud, immediate operational alert (surfaced the same way a job
   failure is, foundation spec §9), never a silent log line, since a failure here means NFR-1 itself
   has been violated somewhere in the stack.
5. **A restatement landing while a chat conversation (S11) is mid-turn** — no special handling
   required; S11's views read live state by construction, so a subsequent question in the same
   conversation simply reflects the corrected number, exactly as the foundation spec's own review
   already concluded.

## 10. Testing strategy

- **Unit** — the sub-period-window-containment logic (`affected_date` → which stored row it maps
  to) against boundary cases (a correction exactly on a sub-period boundary date).
- **Integration** — the decisive test for this whole sub-project: publish a snapshot, apply a
  correction, assert (a) the live figure changed, (b) `cross_check` against the *old* watermark still
  passes, (c) both the original and corrected figures are independently queryable via `GET
  /api/v1/statements/<period>` with different watermarks (FR-26, literally exercised).
- **Contract** — none (no external integration).

## 11. Open parameters (not blocking this spec)

- The periodic `cross_check` sweep's cadence — an operational tuning parameter (e.g. nightly), not
  an architectural one; it runs as a job under the foundation spec's `app/jobs/` contract.
- Customer-facing copy explaining a restatement (e.g. "your March return was corrected on...") — an
  S8 UX concern, not this spec's.
