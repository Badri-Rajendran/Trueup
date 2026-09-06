# Frontend — Structural Spec

Date: 2026-09-05
Status: Draft, pending review
Scope: structural half only — routes, component hierarchy, state/hook boundaries, `services/`
contracts, loading/empty/error states, and testing strategy. Palette, type scale, and visual
treatment are [`docs/specs/frontend/design-system.md`](design-system.md), `frontend-designer`'s
companion spec; this document does not prescribe pixels.
Requirements covered: FR-34–36 (the surfaces requirement), consuming FR-1–33/37–54 as read/write
data — this spec adds no business logic, per `docs/specs/8-surfaces.md`'s own non-goals.
Depends on: [`docs/specs/8-surfaces.md`](../8-surfaces.md) (the only source for routes/payloads —
every endpoint below is copied from it, none invented), [`frontend/CLAUDE.md`](../../../frontend/CLAUDE.md)
(structural rules), [ADR 15](../../decisions/15-session-auth-mfa-tenant-isolation.md) (session auth),
[ADR 20](../../decisions/20-observability-and-realtime-push.md) (SSE), [ADR 5](../../decisions/5-withdrawable-vs-investable-cash.md)
(withdrawable vs. investable cash), [ADR 6](../../decisions/6-as-published-snapshot-cross-check.md)
(as-published vs. live), [ADR 21](../../decisions/21-alpaca-paper-trading-not-broker-api.md)
(simulated account approval).

## 1. Scope calls this spec makes (and defends)

Two items were left formally open by `requirements.md` and `8-surfaces.md` §8. Resolving them here
so the route map below has a fixed shape:

- **Web, not a native mobile app.** The stack is already committed to Vite + React (a web SPA), not
  React Native — building a mobile app would mean a second codebase and a second app-store release
  process inside a six-week window (NFR-11). A responsive layout (`frontend-designer`'s breakpoint
  spec) covers the phone-sized-screen need without that cost. Revisit only if native distribution
  becomes an explicit requirement.
- **Role-gated routes in the same app, not a separate adviser console deployment.** `/admin/*`
  requires `@requires_role("adviser", "admin")` at the API layer already (§4 of `8-surfaces.md`);
  duplicating build, auth, and SSE plumbing into a second app buys nothing for v1 and costs real
  build time. A dedicated adviser bundle remains a clean future split (feature folders already
  isolate `features/admin-*` from customer features) if the adviser surface grows enough to justify
  its own deploy cadence.

**Update:** the customer-directory gap originally flagged here was escalated to `main` and resolved
— `8-surfaces.md` §4 now defines `GET /admin/customers?query=` (paginated, matches email, and name
once S2 carries one). The route map and adviser component list below include the resulting
directory screen.

## 2. Route map

Every route below maps to an owning API route (or a small group of them) from `8-surfaces.md` §3/§4.
No screen here reaches for an endpoint that document doesn't define.

### 2.1 Public

| Route | Screen | Calls |
| --- | --- | --- |
| `/login` | Login | `POST /auth/login` |
| `/register` | Register | `POST /auth/register` |

### 2.2 Onboarding (authenticated, pre-approval)

| Route | Screen | Calls |
| --- | --- | --- |
| `/onboarding` | Identity + bank-link wizard (KYC step, bank-link step) | `POST /identity/kyc-sessions`, `GET /identity/status`, `POST /funding/bank-links` |

A single wizard route, not two, because the two steps are sequential and neither is independently
useful before the other — FR-3 hard-gates funding until both KYC and account approval are
`approved` (ADR 21: account approval auto-follows KYC approval, simulated). The route stays
reachable post-approval too, read-only, as the account's identity/bank-link status view (edge case
in §6).

### 2.3 Customer app (authenticated, KYC + account approval both `approved`)

| Route | Screen | Calls |
| --- | --- | --- |
| `/dashboard` | Balance, period return, holdings snapshot | `GET /valuation/balance`, `GET /valuation/returns`, `GET /portfolios/assignment` |
| `/portfolio` | Model detail + assigned model | `GET /portfolios/models`, `GET/POST /portfolios/assignment` |
| `/orders` | Order list | `GET /orders` |
| `/orders/new` | Place order | `POST /orders` |
| `/orders/:id` | Order detail + approval action | `GET /orders/:id`, `POST /orders/:id/approve` |
| `/funding` | Deposit/withdraw, bank-link status, funding history | `POST /funding/deposits`, `POST /funding/withdrawals`, `GET /identity/status` |
| `/transactions` | Full ledger-derived history | `GET /valuation/history` |
| `/lots` | Tax lot detail, gains | `GET /lots` |
| `/statements` | List of published periods | `GET /statements` |
| `/statements/:period` | As-published figures + export | `GET /statements/:period`, `GET /statements/:period/export` |
| `/fees` | Accrual, charge history, dunning state, payment method | `GET /fees`, `POST /payment-methods` |
| `/chat` | NL query assistant | `POST /chat/sessions`, `POST/GET /chat/sessions/:id/messages`, `GET /chat/sessions` |

### 2.4 Adviser (authenticated, `role in {adviser, admin}`)

| Route | Screen | Calls |
| --- | --- | --- |
| `/admin/customers` | Customer directory / search | `GET /admin/customers?query=` (paginated) |
| `/admin/breaks` | Reconciliation break queue, aged | `GET /admin/breaks?status=open` |
| `/admin/breaks/:id` | Break detail + resolve | (detail fields come from the list row — no `GET /admin/breaks/:id` exists in `8-surfaces.md`; resolve only) `POST /admin/breaks/:id/resolve` |
| `/admin/customers/:id` | Aggregated customer view (KYC override, fee/dunning state) | `GET /admin/customers/:id`, `POST /admin/kyc-overrides/:customer_id`, `GET /admin/customers/:id/fees` |

`/admin/customers` is the adviser's landing screen for reaching a customer with no open break and no
ID already in hand — closing the gap §9 (now resolved) originally flagged. `CustomerSummary` rows
from search link straight into `/admin/customers/:id`.

`/admin/breaks/:id` has no dedicated detail fetch in the backend spec — the row selected from
`/admin/breaks` carries its own detail, so the route exists for a stable URL/deep-link but hydrates
from the list response already in hand, refetching the list on navigation-in (e.g. a deep link) if
the row isn't in memory.

## 3. Feature/component hierarchy

Following `frontend/CLAUDE.md`'s feature-based structure — each domain owns its components, hooks,
api calls, and utils; `pages/` stays thin composition.

```
src/
  pages/
    LoginPage.jsx, RegisterPage.jsx
    OnboardingPage.jsx
    DashboardPage.jsx
    PortfolioPage.jsx
    OrdersPage.jsx, OrderNewPage.jsx, OrderDetailPage.jsx
    FundingPage.jsx
    TransactionsPage.jsx
    LotsPage.jsx
    StatementsPage.jsx, StatementDetailPage.jsx
    FeesPage.jsx
    ChatPage.jsx
    admin/BreaksQueuePage.jsx, admin/BreakDetailPage.jsx, admin/CustomerDetailPage.jsx

  features/
    auth/
      components/ LoginForm, RegisterForm
      hooks/ useLogin, useRegister, useSession
      api/ authApi.js
    onboarding/
      components/ KycStep, BankLinkStep, IdentityStatusBanner
      hooks/ useKycSession, useBankLink, useIdentityStatus
      api/ identityApi.js, fundingApi.js (bank-link exchange only)
    portfolio/
      components/ ModelCard, ModelDetail, AssignmentPrompt, HoldingsTable
      hooks/ useModels, useAssignment
      api/ portfoliosApi.js
    orders/
      components/ OrderList, OrderRow, OrderForm, OrderDetail, ApprovalBanner
      hooks/ useOrders, useOrder, usePlaceOrder, useApproveOrder
      api/ ordersApi.js
    funding/
      components/ DepositForm, WithdrawForm, CashSummary (withdrawable vs. investable), FundingHistory
      hooks/ useDeposit, useWithdraw, useCashPolicy
      api/ fundingApi.js
    valuation/
      components/ BalanceCard, ReturnCard, TransactionTable, CompletenessBanner
      hooks/ useBalance, useReturns, useTransactionHistory
      api/ valuationApi.js
    lots/
      components/ LotTable, LotDetail, ProvisionalBadge
      hooks/ useLots
      api/ lotsApi.js
    statements/
      components/ StatementList, StatementDetail, ExportButton
      hooks/ useStatements, useStatementDetail, useStatementExport
      api/ statementsApi.js
    fees/
      components/ AccrualSummary, ChargeHistory, DunningBanner, PaymentMethodForm
      hooks/ useFees, usePaymentMethod
      api/ feesApi.js
    chat/
      components/ ChatWindow, MessageList, MessageInput, ToolTraceDisclosure
      hooks/ useChatSession, useChatStream
      api/ chatApi.js
    admin-breaks/
      components/ BreakQueue, BreakRow, AgingIndicator, ResolveForm
      hooks/ useBreaks, useResolveBreak
      api/ adminBreaksApi.js
    admin-customers/
      components/ CustomerDirectory, CustomerSearchForm, CustomerSummary, KycOverrideForm,
        CustomerFeesPanel, OpenBreakCallout
      hooks/ useCustomerSearch, useCustomerDetail, useKycOverride, useCustomerFees
      api/ adminCustomersApi.js

  components/           # generic reusable UI only: Button, Input, Select, Card, Badge, Table,
                         # StatusPill, EmptyState, ErrorState, Skeleton, Toast
  hooks/                 # cross-cutting: useSession (auth context), useSSE, useIdempotencyKey
  services/
    apiClient.js          # fetch wrapper: base URL, credentials, error normalization
    sse.js                # EventSource wrapper for ADR 20's push channel
  contexts/
    SessionContext.jsx    # current customer/adviser identity, kyc/account-approval status, role
  utils/                  # formatMoney, formatUnits (6dp), formatPeriod, etc. — pure, no React
```

## 4. State and hook boundaries

- **Component state (local):** form field values, a table's current sort/filter, a modal's
  open/closed flag — anything that dies with the component and no sibling needs it.
- **Custom hook state (feature-owned):** every server round-trip. A hook owns one `status` value —
  `'idle' | 'loading' | 'loaded' | 'error'` (or `'submitting' | 'submitted' | 'error'` for actions)
  merged with its data/error, never separate `isLoading`/`isError`/`data` booleans drifting
  independently (`frontend/CLAUDE.md`'s explicit rule). Example: `useOrders()` returns
  `{ status, orders, error, refetch }`.
- **`useEffect` only to sync with something external:** a data fetch on mount/param change, opening
  an SSE subscription, exchanging a Plaid Link token. Never for derived values (a computed total,
  a filtered list) — those are plain expressions during render.
- **Context (survives navigation, app-wide):**
  - `SessionContext` — logged-in identity, role, `kyc_status`/`account_approval_status`. Route
    guards (§2.2/§2.3/§2.4's gating) read this rather than each page re-fetching
    `/identity/status`; it refreshes on login and on any SSE push that names a KYC verdict change
    (ADR 20 — "a KYC verdict records" is one of the three named push events).
  - An SSE connection singleton (`useSSE` in `hooks/`, provisioned once near the app root) — every
    feature subscribes to the channel(s) it cares about (order fills, KYC verdicts, new breaks)
    rather than each screen opening its own `EventSource`.
- **Nothing else survives navigation.** Order drafts, chat scroll position, etc. are re-fetched or
  reset on remount — no global store beyond the two items above. `frontend/CLAUDE.md`'s KISS
  principle: no state-management library until a second real cross-page need appears.

## 5. `services/` API contracts

One `api/*.js` file per feature (per §3), all routed through the shared `services/apiClient.js` for
base URL, session credentials, and error normalization (a non-2xx response becomes a typed error the
calling hook's `status` picks up). Every write below that `8-surfaces.md` marks `Idempotency-Key`
(NFR-14) attaches a client-generated key from `hooks/useIdempotencyKey`, so a retried submit (e.g. a
flaky connection on a deposit) returns the original result rather than duplicating it.

| Feature api file | Endpoints (verbatim from `8-surfaces.md`) |
| --- | --- |
| `authApi.js` | `POST /auth/register`, `POST /auth/login`, `POST /auth/logout` |
| `identityApi.js` | `POST /identity/kyc-sessions`, `GET /identity/status` |
| `fundingApi.js` | `POST /funding/bank-links`, `POST /funding/deposits` (idempotency-keyed), `POST /funding/withdrawals` (idempotency-keyed) |
| `portfoliosApi.js` | `GET /portfolios/models`, `GET/POST /portfolios/assignment` |
| `ordersApi.js` | `GET/POST /orders` (POST idempotency-keyed), `GET /orders/:id`, `POST /orders/:id/approve` |
| `valuationApi.js` | `GET /valuation/balance`, `GET /valuation/returns`, `GET /valuation/history` |
| `lotsApi.js` | `GET /lots` |
| `statementsApi.js` | `GET /statements`, `GET /statements/:period`, `GET /statements/:period/export` |
| `feesApi.js` | `GET /fees`, `POST /payment-methods` |
| `chatApi.js` | `POST /chat/sessions`, `POST/GET /chat/sessions/:id/messages` (POST response is `text/event-stream`), `GET /chat/sessions` |
| `adminBreaksApi.js` | `GET /admin/breaks?status=open`, `POST /admin/breaks/:id/resolve` |
| `adminCustomersApi.js` | `GET /admin/customers?query=` (paginated), `GET /admin/customers/:id`, `POST /admin/kyc-overrides/:customer_id`, `GET /admin/customers/:id/fees` |

Two shapes need hook-level care because the wire format is not a plain JSON response:

- **`chatApi.sendMessage`** consumes SSE token events (`services/sse.js` reused here, not
  duplicated) and resolves once the final event with `{ message_id, tool_calls }` arrives —
  `useChatStream` exposes streaming text plus the final structured trace separately, since
  `ToolTraceDisclosure` only renders the latter and only on request (`8-surfaces.md` §S11: not
  raw SQL by default).
- **`statementsApi.export`** returns a file, not JSON — `ExportButton` triggers a same-origin
  navigation/download rather than a `fetch`-then-parse, since the backend spec (§5 of
  `8-surfaces.md`) describes a downloadable file response.

## 6. Loading, empty, and error states per screen

`frontend/CLAUDE.md` requires all four explicitly; naming them here so no component ships with only
the happy path.

| Screen | Loading | Empty | Error |
| --- | --- | --- | --- |
| Dashboard | Skeleton balance/return cards | n/a — a customer always has an account once authenticated | `CompletenessBanner` distinguishes a stale/missing price (FR-15, never silently substituted) from an expected market holiday (FR-40) — these are two different banners, not one generic "data unavailable" |
| Portfolio | Skeleton model card | No model assigned yet → `AssignmentPrompt` (not an error state — a customer between onboarding and first assignment) | Assignment `POST` failure surfaces inline, form stays filled |
| Orders list | Skeleton rows | "No orders yet" + link to place one | Fetch failure → `ErrorState` with retry |
| Order detail | Skeleton | n/a (route requires a valid `:id`) | 404 → "order not found"; approval action failure keeps the order in `awaiting_approval` with an inline error, never optimistically flips to approved |
| Funding | Skeleton cash summary | No bank linked yet → prompts the onboarding bank-link step, not a bare empty table | Deposit/withdrawal submit failure inline; a bounced deposit (FR-6) is not a submit-time error — it's a later status change on the same obligation, surfaced via `FundingHistory` row state + SSE push, not a toast |
| Transactions | Skeleton table | "No transactions yet" | Fetch failure → retry |
| Lots | Skeleton table | "No lots yet" (pre-first-buy) | Fetch failure → retry; a lot mid-wash-sale-adjustment shows its adjustment, never the raw pre-adjustment gain (S5's explicit warning, carried into `LotDetail`) |
| Statements list | Skeleton | "No periods published yet" (first month not yet closed) | Fetch failure → retry |
| Statement detail | Skeleton | n/a | Export requested for an unpublished period → the backend's explicit "not yet published" response (`8-surfaces.md` §6.1) renders as a distinct message, never a silent fallback to a live-derived figure |
| Fees | Skeleton | No accrual yet (pre-first-valuation-day) | Payment method attach failure inline; `DunningBanner` renders only when `dunning`/`exhausted` state is present — never invented from a generic error |
| Chat | Streaming indicator while tokens arrive | Empty session → suggested-question prompts | Assistant declines-to-answer (FR-54) renders as a normal assistant message, not an error state — a genuine transport/stream failure is the only thing that renders as `ErrorState` |
| Admin customer directory | Skeleton rows while searching | "No customers match" (distinct from the pre-search empty state — no query typed yet) | Fetch failure → retry, query stays in the input |
| Admin breaks queue | Skeleton rows | "No open breaks" (a real, good state — not blank-looking) | Fetch failure → retry |
| Admin break detail | n/a (hydrated from list) | n/a | Resolve submit failure inline, `resolution_note` stays filled |
| Admin customer detail | Skeleton | n/a (route requires valid `:id`) | 404 → "customer not found"; an open break on this customer renders as a prominent callout regardless of any other state (`8-surfaces.md` §6, edge case 2) |

## 7. Real-time (SSE) integration

Per ADR 20: one SSE connection per authenticated session (`hooks/useSSE`), subscribing to whichever
channel(s) the current route's features care about. Three push types exist app-wide — order fill,
KYC verdict, new reconciliation break — each feature reduces the push into its own hook state rather
than a generic "something changed, refetch everything":

- `orders` feature: a fill push updates the matching order row in place (no full refetch).
- `SessionContext`: a KYC/account-approval verdict push updates the gating status directly, so an
  onboarding customer's `/onboarding` screen advances without a manual refresh.
- `admin-breaks` feature: a new-break push prepends a row to the queue (adviser sessions only).

No SSE connection open (tab backgrounded, connection dropped) degrades to nothing — every screen's
own `GET` on mount/refetch is the source of truth regardless of push delivery, per ADR 20's own
stated fallback.

## 8. Testing strategy (Vitest + React Testing Library)

Per `frontend/CLAUDE.md`: one colocated test file per component, none done without a passing test.

- **Generic `components/`** (Button, Input, Table, StatusPill, EmptyState, ErrorState, Skeleton):
  render tests plus interaction tests (click, keyboard, focus-visible) — these are reused
  everywhere, so their accessibility contract is tested once, thoroughly, here rather than
  re-verified per feature.
- **Feature presentational components** (OrderRow, LotDetail, AccrualSummary, etc.): render tests
  per data shape — populated, empty-eligible fields, and a provisional/adjusted/dunning variant
  where the domain has one (e.g. `LotDetail` with and without a wash-sale adjustment).
  Loading/empty/error variants render tests per §6's table — every named state gets its own test
  case, not just "renders without crashing."
- **Feature hooks**: interaction tests against a mocked `api/*.js` — success, error, and (for
  idempotency-keyed writes) a simulated retry-with-same-key returning the original result rather
  than a duplicate.
- **Forms** (DepositForm, OrderForm, KycOverrideForm, PaymentMethodForm): interaction tests —
  validation errors, submit-disabled-while-submitting, and the submit-failure-keeps-input-filled
  behavior named in §6.
- **`ChatWindow`/`useChatStream`**: an interaction test against a mocked SSE stream — partial
  tokens render incrementally, the final structured event closes the stream and exposes
  `tool_calls` only when `ToolTraceDisclosure` is expanded.
- **Route guards** (`SessionContext`-driven redirects: unauthenticated → `/login`, KYC/approval
  incomplete → `/onboarding`, non-adviser hitting `/admin/*` → redirected, not just hidden):
  tested at the router/context level, not per page, since the guard logic is shared.
- No end-to-end/Playwright layer is this spec's concern — `frontend/CLAUDE.md` names Vitest+RTL as
  the frontend's own layer; end-to-end coverage is a separate cross-stack concern for whenever
  implementation exists to run it against.

## 9. Open questions (escalated to `main`)

1. ~~No adviser customer-search/list endpoint~~ — resolved. `main` added `GET
   /admin/customers?query=` to `8-surfaces.md` §4; the directory screen and its components are
   folded into §2.4/§3 above.
2. **`GET /admin/breaks/:id` does not exist** — `/admin/breaks/:id` in the route map (§2.4) hydrates
   from the list response already in hand; a cold deep-link to that URL has no dedicated fetch to
   fall back to and would need to refetch the whole list and find the row. Worth confirming this is
   acceptable rather than adding a detail-fetch endpoint later.

Coordinated with `frontend-designer`: sent the feature/component inventory (§3) once this first pass
was stable, so their palette/type-scale spec can react to the real component set (in particular the
data-dense screens — Transactions, Lots, admin Breaks queue — versus the simple-form screens —
Funding, KYC/bank-link, Order placement) rather than a hypothetical one.
