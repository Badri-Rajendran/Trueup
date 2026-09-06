# Frontend completion — design

## Context

The frontend (`frontend/src`) is not a greenfield build: five prior phases produced ~204 files
across 12 customer routes and 4 admin routes, a 93-token design system with zero hardcoded-color
violations, a clean `apiClient.js` (CSRF, idempotency keys, RFC 9457 error normalization), and a
passing `npm run lint` / `npm run build`. What's missing is real: **zero test files** despite
`frontend/CLAUDE.md`'s "no component is done without a test," and **six domains built against
`mockClient.js` instead of the API** — committed under a commit literally titled "Phase 4 - mocked
domains." `App.jsx`'s own comment names them: portfolio, lots, fees, chat, admin customers,
statement export.

A three-way audit (mock inventory, backend API surface, spec conformance) found the six mocks split
two ways:

- **Backend already has the route** (portfolio, fees, chat, admin customer fees) — pure frontend
  wiring gaps.
- **No backend route exists at all** (lots, admin customers directory/detail/KYC-override,
  statement export) — these are exactly S8's F10 finding from the earlier backend audit: six
  documented-but-unbuilt routes.

Two more gaps surfaced beyond the six named mocks: `structure.md §7` mandates a `hooks/useSSE` for
real-time push (order fill, KYC verdict, new break) built on `S12 §6`/`ADR 20`'s Redis Pub/Sub
fan-out — neither the backend endpoint nor the frontend hook exists, only chat has SSE. And the fee
payment-method form collects a card brand/last-4 as plain strings instead of tokenizing through
Stripe Elements, despite `@stripe/stripe-js` already being a dependency and `GET /identity/config`
already serving the publishable key needed to mount it.

The user's directive — "nothing should be mocked, ensure everything is finished" — was tested
against three scope questions, each decided in favor of the larger, more complete option:

1. **Missing backend routes**: build them (not leave three domains mocked, not remove them).
2. **Order-form pricing**: reuse `GET /portfolios/models` for the security picker; the customer
   enters `reference_price` (already a required API field) rather than inventing a quote source.
3. **Test depth**: exhaustive — one colocated test file per component, matching the literal text of
   `frontend/CLAUDE.md` and `structure.md §8`, not a risk-prioritized subset.
4. **Real-time push**: build the full fan-out (backend SSE endpoints + Redis Pub/Sub publish sites +
   frontend `useSSE` + its three consumers), not defer it.
5. **Stripe Billing**: wire real Stripe Elements, tokenizing in the browser so card data never
   touches Trueup's servers.

This spec is the design for closing all of it. It does not re-litigate those five decisions or the
backend remediation plan already executed and merged (`carefully-and-thoroughly-read-joyful-riddle`
plan, PRs #5–#6) — it starts from `main` at that point.

## Scope

**In scope:**
- Six new/extended backend routes (S8 F10): `/lots`, `/statements/<period>/export`,
  `/admin/customers`, `/admin/customers/<id>`, `/admin/kyc-overrides/<customer_id>`,
  `/admin/customers/<id>/fees` (the last already partially served by `GET /fees?customer_id=`).
- Real-time push backend: `GET /api/v1/events/stream`, `GET /api/v1/admin/events/stream`, and the
  three publish sites (`OrderService`, `KycService`/`AccountApprovalService`,
  `ReconciliationService`), per `S12 §6`'s already-complete wire design.
- Frontend: replace all six `mockClient`-backed `api/*.js` modules with real `apiClient` calls;
  build `hooks/useSSE` and its three feature consumers; replace `useChatStream`'s fake token-split
  with a real `fetch` + `ReadableStream` consumer of the existing chat SSE endpoint; replace
  `PaymentMethodForm`'s plain-string capture with Stripe Elements.
- Vitest + React Testing Library installed and wired into `npm test` and `Makefile`; one colocated
  test file per component/hook/api module/route-guard, per `structure.md §8`.

**Out of scope (explicitly deferred, not silently dropped):**
- CI/CD wiring for the frontend (Phase 3 of the backend plan already covers this ground generally;
  extending it to frontend jobs is a follow-up once tests exist to run).
- Azure deployment of the frontend container (Dockerfile already exists from Phase 0; deploying it
  is Phase 5 of the backend plan, unchanged).
- Anything in `docs/specs/frontend/structure.md §9`'s still-open question 2 (`/admin/breaks/:id`
  hydrating from the list vs. a dedicated fetch) — no new information changes that answer; current
  hydrate-from-list behavior stands.

## Architecture

### A. Backend: the six S8 routes

All five new endpoints follow the existing controller pattern exactly (Pydantic request/response
views in `app/views/`, a thin controller in `app/controllers/api/` or `app/controllers/admin/`, a
service method, `@requires_role`/inline ownership matching neighboring routes, `@audited` on every
privileged write per `ADR 15`).

- **`GET /api/v1/lots`** (customer route, `S8 §3`) — new `LotsService` read method returning open
  and (optionally, `?include_closed=`) closed lots for the caller's `customer_id`, with
  `is_provisional` computed from `designation_window_closes_at` vs. now, and wash-sale adjustment
  fields surfaced per `TaxLot.adjusted_basis`. Reuses `TaxLotRepository` (`app/models/ledger/tax_lot.py`)
  already built for S5 — no new repository method beyond a customer-scoped list query.

- **`GET /api/v1/statements/<period>/export`** (`S8 §5`, FR-36) — a new controller action beside the
  existing `statements.py` routes. Reads the published snapshot exactly as `get_statement` does
  (never a live recompute — same "not yet published" 404 if absent, per spec edge case 1), plus the
  period's realized lot consumptions (S5) including `is_provisional` and any
  `wash_sale_adjustment` rows, and renders CSV (`text/csv`, `Content-Disposition: attachment`). No
  PDF (spec names it out of scope for v1).

- **`GET /api/v1/admin/customers`** (`S8 §4`) — paginated directory using the existing
  `app/core/pagination.py` helper; `?query=` matches email case-insensitively (name matching is
  deferred per the spec's own note — S2 carries no name field yet). `@requires_role("adviser",
  "admin")`.

- **`GET /api/v1/admin/customers/<id>`** — aggregates existing read paths under the adviser RLS
  branch: `ValuationService.value_book` (the *same* call `/valuation/balance` makes — spec edge case
  4's "must agree exactly" requirement, satisfied by literally not duplicating the aggregation), KYC
  and account-approval status, and **any open reconciliation break for this customer**, surfaced as
  a prominent field per spec edge case 2 — not a separate fetch the frontend has to remember to make.

- **`POST /api/v1/admin/kyc-overrides/<customer_id>`** — the concrete route for S2 §9's open
  parameter. Only valid when `customer.kyc_status == REJECTED` and the latest `KycSession.attempt_number
  >= KYC_MAX_ATTEMPTS` (the existing locked-rejected condition already computed in
  `kyc_service.py:47`, not a new column) — resets `kyc_status` to `pending` and allows a fresh
  `KycSession`. `@audited("identity.kyc.override")`.

- **`GET /api/v1/admin/customers/<id>/fees`** — thin adviser-scoped wrapper over the same
  `FeeChargeService` read path `GET /fees?customer_id=` already uses; kept as its own route per the
  spec's route table (adviser fee view vs. customer fee view are named separately in `S8 §4`), but
  implemented as a one-line delegation, not a second aggregation.

`/identity/status/<customer_id>` also gets a small extension here: distinguish "rejected, locked"
from "rejected, resubmittable" in its response (spec edge case 3), using the same
`attempt_number >= max_attempts` check the override route reads, rather than inventing a new status
value the customer-facing copy has to interpret.

### B. Backend: real-time push (S12 §6 / ADR 20)

The wire design is already fully specified — this implements it, not designs it:

- Two SSE routes: `GET /api/v1/events/stream` (customer, ownership-scoped) and
  `GET /api/v1/admin/events/stream` (adviser, role-scoped) — long-lived generators identical in
  shape to `chat.py`'s existing `send_message` SSE handler, subscribing to
  `customer:<customer_id>:events` or `adviser:events` via the existing `redis.Redis` client
  (`app/extensions.py:make_redis`) on connection open, unsubscribing on disconnect.
- Message shape fixed by spec: `{event_type, entity_id, summary}` — a pointer, never the entity
  itself; the frontend's reaction is always a re-fetch of the relevant `GET` endpoint.
- Three publish sites, each firing **after** its own commit (never inside the transaction, per
  S0 §5's no-I/O-in-a-transaction rule, restated explicitly by S12 §6): `OrderService` on a fill or
  terminal `order_event`; `KycService`/`AccountApprovalService` on a status change; `ReconciliationService`
  on opening a `reconciliation_break`. Adding a fourth is not in scope — three matches the spec's
  named list exactly.
- No new infra: same Redis instance already used for sessions/rate limits (ADR 13/15's "never holds
  financial state" is preserved — a Pub/Sub message is an ephemeral pointer, not a fact of record).

### C. Frontend: mock removal

Each of the six `api/*.js` modules is rewritten to call `apiClient` instead of `mockClient`, matching
the request/response shapes the backend audit already pinned down exactly (money/units/price as
fixed-point strings, `code`-only error bodies). Two need a field-mapping layer because names differ
from what the mock invented:

- `feesApi.js` — backend's `accrual_to_date` / `high_water_mark.peak_value` map onto the same UI
  concepts the mock called `accrual.month_to_date_gain` etc.; the mapping lives in the api module,
  not spread across components.
- `chatApi.js` / `useChatStream.js` — replaced with a real `fetch(..., {method: 'POST'})` +
  `response.body.getReader()` loop parsing `data: {...}\n\n` frames per the three documented shapes
  (`token`, `completed`, `error`); `EventSource` cannot be used since the endpoint is a CSRF-bearing
  POST.
- `portfoliosApi.js` — drops the fabricated `getSecurities()` price table entirely;
  `OrderForm` now sources its security picker from `GET /portfolios/models`'s
  `target_weights[].{security_id, symbol}` and asks the customer for `reference_price` directly
  (decision 2 above) — the field the API already requires, so no contract change.
- `lotsApi.js`, `adminCustomersApi.js`, `statements/export` — become thin real clients once §A's
  routes exist; no mapping needed, response shapes are authored to match the frontend's existing
  expectations since both are built in this change.

`mockClient.js` is deleted once its last consumer is migrated — not left as unreferenced dead code.

### D. Frontend: `useSSE` and its consumers

One hook (`src/hooks/useSSE.js`), one connection per authenticated session, opened once by
`SessionContext` (mirroring how `useChatStream` already manages its own connection) and exposing a
subscribe-by-`event_type` API so a feature registers a callback rather than the hook knowing about
every feature. Three consumers, exactly as `structure.md §7` specifies:

- `orders` feature: a `fill` push re-fetches and patches the matching row in place — no full list
  refetch.
- `SessionContext`: a KYC/approval push re-fetches `GET /auth/session` so onboarding gating updates
  without a manual reload.
- `admin-breaks` feature: a new-break push re-fetches the list's first page and prepends any row not
  already present.

No connection (tab backgrounded, disconnected) degrades to nothing — every screen's own `GET` on
mount stays the source of truth, exactly as ADR 20 requires.

### E. Frontend: real Stripe Elements for billing

`PaymentMethodForm` mounts Stripe Elements (`@stripe/stripe-js`, already a dependency) using the
publishable key from the existing `GET /identity/config`, collects the card via Stripe's own
`CardElement` (never touching Trueup's servers with raw card data), and submits the resulting
`payment_method_id` to the existing `POST /payment-methods`. This is the same integration pattern
`OnboardingPage`'s Stripe Identity step already uses for the KYC provider key, applied to Billing.

### F. Testing

Vitest + `@testing-library/react` + `@testing-library/jest-dom` + `jsdom`, wired as `npm test` in
`package.json` and a `frontend-test` target in the root `Makefile` (mirroring the backend's
`test-unit`/`test-integration` pattern). Per `structure.md §8`, colocated one-file-per-unit:

- **Generic `components/`** (13 dirs): render + interaction + keyboard/focus-visible tests — the
  shared accessibility contract, tested once.
- **Feature components** (~60 files across 12 features): render tests per data shape, including the
  provisional/adjusted/dunning variant named per-domain in `design-system.md §8`.
- **Feature hooks** (~20 files): success/error/idempotent-retry against a mocked `api/*.js`.
- **api modules** (13 files): request-shape and error-mapping tests against a mocked `fetch`.
- **Forms**: validation, submit-disabled-while-submitting, submit-failure-keeps-input-filled.
- **`ChatWindow`/`useChatStream`**: mocked SSE stream, incremental token rendering,
  `tool_calls` disclosure.
- **Route guards** (`SessionContext`, `guards.jsx`): tested once at the router/context level.
- **Loading/empty/error states**: the `structure.md §6` table is the checklist — each named cell
  becomes an explicit test case, not an implicit "renders" assertion.

## Data flow / error handling

No change to the established contracts: `apiClient.js`'s CSRF/idempotency/error-normalization stays
the single point of contact; every error still surfaces as `ApiError{status, code, ...}` and every
new form follows the existing inline-error, keep-input-filled pattern already used by
`DepositForm`/`WithdrawForm`. The two new backend surfaces (admin aggregation, SSE) both read
already-existing services rather than introducing a second source of truth, satisfying spec edge
case 4 (`/valuation/balance` and `/admin/customers/<id>` must agree exactly).

## Testing (verification for this change itself)

- Backend: new routes get the same four-layer coverage (`tests/unit`, `tests/integration`,
  `tests/api`, `tests/contract` where applicable) as every existing S8 route; `make check` green;
  Alembic round-trip if any schema changes (none anticipated — all new routes read existing tables).
- Frontend: `npm test` green, `npm run lint`, `npm run build` green; manual smoke of the full loop
  (register → KYC → bank link → deposit → assign portfolio → order → SSE fill push → statement →
  export) against a running `make up && make dev` backend.
- `mockClient.js` has zero remaining importers before deletion — verified by grep, not assumption.
