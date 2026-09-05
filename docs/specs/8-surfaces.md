# S8 — Surfaces: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-34–36
Depends on: S1–S7, S9, S10 (this spec is a consumer of every prior sub-project's data; it defines no
new economic mechanism of its own), S11 (the chat assistant is an alternative surface over the same
data, built separately per its own spec)
Consumed by: nothing — this is the outermost layer

Mobile-vs-web and adviser-console-vs-plain-admin remain formally open per `requirements.md` — this
spec is unaffected by either answer, since it defines the API surface both would consume, not the
frontend technology itself (`frontend/CLAUDE.md` owns that when it's decided).

## 1. Purpose

The audit that produced this spec found no endpoint enumeration existed anywhere — only a handful of
illustrative examples in the foundation spec's surface-map sketch. This spec is that enumeration:
every customer-facing and adviser-facing route the platform needs, cross-referenced against each
owning sub-project so nothing here re-invents a mechanism another spec already defined.

## 2. Non-goals

- Any new business logic — every route below calls into a service another spec already specifies;
  this document lists the surface, it does not add behavior.
- The React component structure — `frontend/CLAUDE.md`'s own process, once mobile-vs-web is decided.
- Statement PDF rendering detail — FR-36's export format is a presentation concern; this spec
  defines the endpoint and what data it returns, not the file layout.

## 3. Customer-facing routes (`/api/v1/*`)

All require `@login_required` + `@requires_ownership("customer_id")` (foundation spec §7.2) unless
noted. Grouped by owning sub-project — no route appears twice.

| Route | Method | Owning spec | Purpose |
| --- | --- | --- | --- |
| `/auth/register`, `/auth/login`, `/auth/logout` | POST | foundation §7.1 | session lifecycle |
| `/identity/kyc-sessions` | POST | S2 §6 | start Stripe Identity verification |
| `/identity/status` | GET | S2 §6 | KYC + account-approval status |
| `/funding/bank-links` | POST | S2 §6 | Plaid Link token exchange |
| `/funding/deposits`, `/funding/withdrawals` | POST | S2 §6 | funding actions (idempotency-keyed) |
| `/portfolios/models` | GET | S9 §3 | the four model portfolios' public descriptions |
| `/portfolios/assignment` | GET, POST | S9 §3 | view/select the customer's assigned model (FR-7) |
| `/orders` | GET, POST | S3 §6 | place/list orders |
| `/orders/<id>` | GET | S3 §6 | order detail |
| `/orders/<id>/approve` | POST | S3 §6 | approve a threshold-gated order (FR-10) |
| `/valuation/balance` | GET | S4 §7 | current balance (FR-18) |
| `/valuation/returns` | GET | S4 §7 | period return, live (FR-18) |
| `/valuation/history` | GET | S4 §7 | transaction history (FR-18) |
| `/lots` | GET | S5 (via a read endpoint this spec adds — S5 itself defines no HTTP surface, per its own non-goals) | tax lot detail, gains, provisional flags |
| `/statements` | GET | S6 §8 | list published periods |
| `/statements/<period>` | GET | S6 §8 | as-published figures for one period |
| `/statements/<period>/export` | GET | this spec (FR-36, built on S6's snapshot + S5's lot data) | tax-time export file |
| `/fees` | GET | S10 §7 | accrual/charge/dunning status |
| `/payment-methods` | POST | S10 §7 | Stripe payment method attach/update |
| `/chat/sessions`, `/chat/sessions/<id>/messages` | POST/GET | S11 §6 | the NL query assistant (its own spec, listed here only for completeness) |

**FR-34's approval action** is not a separate route — it is `/orders/<id>/approve` above, since
"approving trades above threshold" is an order-lifecycle action (S3's), not a distinct surfaces-owned
mechanism; listing it twice under two sub-projects would violate this spec's own "no route appears
twice" rule.

## 4. Adviser-facing routes (`/api/v1/admin/*`)

All require `@login_required` + `@requires_role("adviser", "admin")`; privileged actions additionally
carry `@audited` (foundation spec §7.2/ADR 15).

| Route | Method | Owning spec | Purpose |
| --- | --- | --- | --- |
| `/admin/customers/<id>` | GET | this spec (aggregates S1/S4 read views under ADR 17's adviser RLS branch) | a single customer's full account view |
| `/admin/breaks` | GET | S7 §8 | reconciliation break queue, aged (FR-31) |
| `/admin/breaks/<id>/resolve` | POST | S7 §8 | manual resolution (FR-44), `@audited` |
| `/admin/kyc-overrides/<customer_id>` | POST | S2 §9's own open parameter, resolved here as the concrete route: reopens a locked-`rejected` KYC status | `@audited` |
| `/admin/customers/<id>/fees` | GET | S10 §7 | adviser view of a customer's fee/dunning state |

The adviser console's own front-end packaging (a separate app vs. role-gated routes in the same app)
is unaffected by this table — the foundation spec's blueprint split (`api/` vs `admin/`) is correct
either way, per that spec's own §14.

## 5. Statement export (FR-36, the one genuinely new mechanism this spec adds)

```
GET /statements/<period>/export:
    snapshot = S6.published_snapshot for (customer_id, period)   -- as-published, never live,
                                                                     since a tax export must reflect
                                                                     what was actually reported, not
                                                                     a figure that could still move
    lots = S5.tax_lot / lot_consumption rows realized within the period, including is_provisional
           flags (S5 §4) and any wash_sale_adjustment entries (S5 §5) — never the raw
           realized_gain_loss before wash-sale adjustment (S5's own explicit warning)
    render as a downloadable file (CSV in v1; a PDF an accountant would accept is the brief's own
    stretch-ladder item, out of scope here)
```

A provisional lot consumption (its designation window hasn't closed yet) still appears in the
export, clearly labelled provisional — never omitted, since omitting a real transaction would
understate the export rather than merely flag it as pending finalization.

## 6. Edge and corner cases

1. **A customer requests an export for a period that was never published** — `GET
   /statements/<period>/export` returns a clear "not yet published" response rather than falling
   back to a live-derived export; a tax export is, by definition, a request for the as-published
   figure (§5), and one that doesn't exist yet is not silently substituted with a live one.
2. **An adviser views `/admin/customers/<id>` for a customer with an open reconciliation break** —
   the aggregated view must surface that fact prominently (a break affecting the very account being
   viewed is exactly the situation FR-31's aging indicator exists to make visible, not just on the
   dedicated breaks screen).
3. **A customer whose KYC was locked to `rejected` after exhausting attempts (S2 §3.2) requests
   status** — `/identity/status` must distinguish "rejected, contact support" from "rejected, you may
   resubmit" — the former only an adviser's `/admin/kyc-overrides` action can change, and the
   customer-facing copy must not imply a self-service resubmission path that doesn't exist once
   locked.
4. **Two different roles hitting the same underlying customer data through different routes**
   (`/valuation/balance` vs. `/admin/customers/<id>`) must return figures that agree exactly — both
   ultimately call the same S4 `ValuationService.value_book`, never two independently-implemented
   aggregations that could drift apart (DRY, and a correctness requirement given NFR-7's grading
   emphasis).

## 7. Testing strategy

- **API** — every route in §3/§4 gets an authn/authz/ownership/role test (a customer session must
  get 403 on every `/admin/*` route, never 404, consistent with the general error-response
  discipline elsewhere in this design); the export endpoint's "not yet published" rejection path.
- No new unit/integration/contract layers — this spec calls existing services, it does not introduce
  new ones beyond the export assembly logic (§5), which itself is a thin read-only aggregation with
  no independent business rule to unit-test beyond "does it call the right lower-level functions and
  format their output," verified at the API-test layer.

## 8. Open parameters (not blocking this spec)

- Mobile vs. web, and a dedicated adviser console vs. role-gated routes in the customer app — both
  formally open per `requirements.md`; this spec's route table is correct under either resolution.
- Statement export format beyond CSV (a proper tax-accountant-ready PDF) — the brief's own
  stretch-ladder item, out of v1 scope.
