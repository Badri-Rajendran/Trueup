# Trueup full-stack rebuild — SDD execution plan

Source of truth this plan argues from: `/Users/badrinarayanan/.claude/plans/yes-the-new-design-purring-sutherland.md`
(the plan-mode plan the user approved) and, beneath it, `docs/specs/frontend/{design-system,structure}.md`,
`docs/specs/08-surfaces.md`, `docs/specs/12-production-operations.md` §6, `docs/decisions/{01,04,05,20,26,27}*.md`,
and `docs/requirements/requirements.md`. Where this plan and one of those disagree, the spec wins;
flag the conflict in the ledger rather than silently picking one.

Branch: `feature_ui_revamp_fullstack` off `main`, in an isolated worktree. Do not work on `main` or
on any other branch. Chat (`ChatPage.jsx` and everything under `features/chat/`) is explicitly kept
exactly as it is today — no task in this plan touches its behavior, only (Task 7) the shell CSS
around it.

Tasks execute **in numeric order, one at a time** (never dispatch two implementers in parallel).
The order already reflects the dependency graph — do not reorder without a ledgered ruling.

## Global Constraints

These bind every task. Copy the relevant subset verbatim into each task reviewer's context.

### Backend conventions (`backend/CLAUDE.md`)
- Layering, strictly one direction: `controllers → services → models → core`; `services` reach
  external providers only through `Protocol`s in `app/integrations/ports.py`, never a concrete
  adapter — enforced by `import-linter` (`backend/.importlinter`), run via `uv run lint-imports`.
- Every money/unit/price value uses `Money`/`Units`/`Price` from `app/core/money.py` — never a bare
  `Decimal`, never a float. On the wire, every `Money`/`Units`/`Price` field and every `Decimal`
  with an explicit `@field_serializer(..., when_used="json")` is a **JSON string** — `"1234.5600"`,
  not `1234.56`. Reject a float `amount`/`quantity`/`price` in a request body; require a string.
- Response schemas live only in `app/views/`, as explicit Pydantic models — never serialize an ORM
  entity directly, and `app/views/` may import `app/core` only (not `app/models`, not `app/services`).
- Error body is always exactly `{type: "about:blank", title, status, code, correlation_id}` — no
  `detail` field ever leaves the server. New error codes are added as a specific `AppError` subclass
  or an explicit code string on a `ValidationError`/`NotFoundError`/etc.; never invent a new shape.
- Every new route needs its own `@limiter.limit("N per minute")` — there are no default limits.
  Match the limit style of the nearest analogous existing route (reads 60/min, writes 10-30/min).
- Every repository read of a bitemporal aggregate takes `as_of: Watermark` with no default.
- Canonical four-file pattern for a new read-only endpoint (copy this shape exactly): controller in
  `app/controllers/api/<name>.py` (blueprint, `@limiter.limit(...)`, role/ownership check, opens a
  `with <X>UnitOfWork(...) as uow:` block, returns `jsonify(view.model_dump(mode="json")), 200`) →
  view in `app/views/<name>.py` (Pydantic schemas only) → service in
  `app/services/<domain>/<name>_service.py` (constructor-injected UoW, one responsibility) →
  registered in `app/__init__.py` (import near the top + `app.register_blueprint(...)` in
  `create_app`) → test in `tests/api/test_<name>.py` using the `api_client` fixture
  (`tests/api/conftest.py`), asserting the exact whole response body, not just status code.
- Gates before any backend task is done: `uv run pytest` (all of `tests/unit`, `tests/integration`,
  `tests/api`), `uv run mypy --strict app`, `uv run ruff check app tests`, `uv run lint-imports`.
  Coverage floor is 77% (`pyproject.toml`). Tests need Postgres on `:5433` and Redis on `:6380/1`
  (`docker compose up -d` from the repo root) — never SQLite.
- Any schema change ships an Alembic migration in the same commit
  (`uv run alembic revision --autogenerate -m "..."`, then hand-review it, then
  `uv run alembic upgrade head` to prove it applies cleanly).
- Auth/session facts that affect API design: session cookie is `SameSite=Strict`, no CORS is
  configured — same-origin only. CSRF token is issued as `csrf_token` in login/session responses
  and sent back as header `X-CSRFToken` on every mutating request; a missing/bad token is **400**,
  not 401/403. A staff (`adviser`/`admin`) session must pass `?customer_id=<uuid>` on every read a
  customer-scoped route serves; a customer session never does (reads `flask.session["_user_id"]`).

### Frontend conventions (`frontend/CLAUDE.md`)
- Structure: `src/features/<domain>/{api,hooks,components}/`, `src/pages/` (thin route screens that
  compose features), `src/components/` (generic reusable UI — all 15 existing components: Badge,
  Button, Card, DetailFields, EmptyState, ErrorState, Icon, Input, Select, SimulatedBadge, Skeleton,
  StatusPill, Table, Toast, UnitsValue — are **IA-agnostic and must not be structurally rewritten or
  redesigned** by this plan; reuse them as-is. This does not forbid a purely additive extension a
  later task's own data genuinely requires and that leaves every existing consumer's behavior
  unchanged — e.g. Task 1 adding new entries to `Icon/paths.js` without touching any existing path.
  If a task's brief explicitly calls for such an addition, follow the brief; if you find yourself
  wanting to change an existing prop, class, or behavior on one of these 15 components, that is the
  line — stop and report it as a concern rather than doing it), `src/hooks/` (cross-feature hooks),
  `src/services/` (network/config/external integration), `src/utils/` (pure JS, no React).
- **Canonical data hook shape** — copy this exactly for every new read hook (verbatim reference:
  `frontend/src/features/valuation/hooks/useBalance.js`):
  ```js
  const IDLE = { status: 'idle', <domainField>: null /* or [] */, error: null }
  export function useX(...) {
    const [state, setState] = useState(IDLE)
    const refetch = useCallback(async () => {
      setState((prev) => ({ ...prev, status: 'loading', error: null })) // keeps last-good data
      try {
        const data = await xApi.get(...)
        setState({ status: 'loaded', <domainField>: <mapped data>, error: null })
      } catch (error) {
        setState({ status: 'error', <domainField>: null, error })
      }
    }, [/* query deps */])
    useEffect(() => { refetch() }, [refetch])
    return { ...state, refetch }
  }
  ```
  Mutation hooks mirror this with `status: 'idle'|'submitting'|'submitted'|'error'`, and **re-throw**
  on failure (read hooks never throw). `error` is always the raw `ApiError` instance from
  `src/services/apiClient.js` — map it to text only at the component boundary via
  `getErrorMessage(error)` from `src/utils/apiErrorMessage.js`, fed into
  `<ErrorState description={...} onRetry={refetch} />`.
- `src/services/apiClient.js` is the only fetch wrapper — `apiClient.get/post/patch(path, body, {
  idempotencyKey })`, throws `ApiError { status, code, type, correlationId }`. Do not add a second
  fetch wrapper or call `fetch` directly anywhere outside `apiClient.js` and the chat SSE reader
  (which is intentionally separate — do not touch it).
- Every page renders four states explicitly: loading (a named-shape `Skeleton`, never a bare
  spinner), empty (`EmptyState`, `variant="good"` when empty is the desired state), error
  (`ErrorState` with `onRetry`), success. This is a component-test requirement, not a nicety.
- Gates before any frontend task is done: `npm run lint` (oxlint), `npm run build`, and — from
  Task 1 onward — `npm test` (Vitest). A component is not done without a test covering render,
  interaction, and loading/empty/error states, per `frontend/CLAUDE.md`.
- **The Chat layout contract, do not break it**: `.tu-app-layout` (`flex column`) →
  `.tu-app-layout__main { display:flex; flex-direction:column; flex:1; min-height:0 }` → down
  through `.tu-chat-page` → `.tu-chat-window__messages { overflow-y:auto }` is what lets the chat
  transcript scroll internally instead of the whole page scrolling. Any wrapper this plan puts
  around `<Outlet/>` must carry those same four properties on the element that plays `__main`'s role.

### Commit / PR discipline
- One commit (or a small tight series) per task, on `feature_ui_revamp_fullstack`. Do not open a PR
  per task — the whole branch is one PR at the end, per the root `CLAUDE.md`'s PR process, opened
  only after `finishing-a-development-branch` is invoked at the very end of this plan.
- Every commit message ends with the attribution lines the controller session was given (ask the
  controller if unsure — do not fabricate an attribution block).
- Never commit `.env`, `backend/.venv/`, `frontend/node_modules/`, or `frontend/dist/`.

---

## Task 1: Frontend foundations — Vitest, extended type tokens, theme toggle

This is the first frontend task and the only one with no dependency on any backend task. It
unblocks every later frontend task's test-writing requirement.

**1a. Install the test runner.** `frontend/package.json` currently has no test infrastructure at
all — no `vitest`, no `@testing-library/*`, no `test` script, despite `frontend/CLAUDE.md`
documenting `npm test`. Add as devDependencies: `vitest`, `@vitest/coverage-v8`, `jsdom`,
`@testing-library/react`, `@testing-library/user-event`, `@testing-library/jest-dom`. Add scripts
`"test": "vitest run"` and `"test:watch": "vitest"`. Add a `test` block to `vite.config.js`
(`environment: 'jsdom'`, `setupFiles: ['./src/test/setup.js']`, `globals: true`). Create
`src/test/setup.js` importing `@testing-library/jest-dom` matchers and mocking `window.matchMedia`
(needed for `prefers-color-scheme`/`prefers-reduced-motion` — jsdom has no real implementation).
Write one trivial passing test (e.g. for the existing `formatMoney` in `src/utils/format.js`) to
prove the harness works end-to-end.

**1b. Extend the type scale — additive only.** In `frontend/src/styles/tokens.css`, add three new
tokens to the existing `:root` block, without touching any of the 17 existing color tokens or the
existing type tokens (`--font-size-display` etc. stay exactly as they are):
```css
--font-size-display-xl: 56px; --line-height-display-xl: 60px; --font-weight-display-xl: 600;
--font-size-title: 28px;      --line-height-title: 34px;      --font-weight-title: 600;
--font-size-section: 20px;    --line-height-section: 28px;    --font-weight-section: 600;
```
`display-xl` and `title`/`section` use `var(--font-serif)` when applied (that's a consumer-side
choice in later tasks, not a new font-family token here). Do not add these tokens to the dark-mode
blocks — type tokens aren't theme-dependent in this codebase (only color tokens are duplicated
per-theme); check `tokens.css`'s existing structure and follow its own pattern exactly.

**1c. Theme context + toggle.** `docs/specs/frontend/design-system.md` §2.2 requires "an explicit
in-app toggle persisted per user" and it has never been built — `data-theme` is currently never set
by any JS anywhere in the codebase (confirmed by grep). `tokens.css` already has both
`@media (prefers-color-scheme: dark) { :root:not([data-theme='light']) {...} }` and
`:root[data-theme='dark'] {...}` blocks waiting for the attribute to ever be set.

Create `src/contexts/ThemeContext.jsx`: `ThemeProvider({children})` reads `localStorage` key
`trueup.theme.v1` (values `'light'|'dark'|'system'`, default `'system'`) wrapped in try/catch (a
private-mode or storage-disabled browser must not throw — fall back to `'system'` silently), applies
`document.documentElement.setAttribute('data-theme', value)` for `'light'`/`'dark'`, or
`removeAttribute('data-theme')` for `'system'`, on mount and on every change; writes back to
`localStorage` in a try/catch on every change. Exposes `{theme, setTheme}` via `useTheme()`.

Create `src/components/ThemeToggle/{ThemeToggle.jsx,ThemeToggle.css,index.js}` — a single icon
button that cycles light → dark → system → light on click, following the existing `Icon` component's
16×16 stroke-path convention (add three new paths — sun, moon, a system/monitor glyph — to
`src/components/Icon/paths.js` rather than inventing a separate icon mechanism), `aria-label`
reflecting the *next* state it will switch to (e.g. "Switch to dark theme"), visible focus ring per
the existing `:focus-visible` global rule. Do not mount it in the app shell yet — that's Task 7. Just
build it and its own component test (renders, cycles on click, persists to `localStorage`, falls
back cleanly when `localStorage` throws).

**Do not** touch `AppLayout.jsx`, `App.jsx`, or any page file in this task.

**Report:** the exact `npm test` output (pass count), confirmation the trivial `formatMoney` test
and the `ThemeToggle` test both pass, and confirmation `npm run build` still succeeds with the new
tokens present.

---

## Task 2: Backend — Watchlist read endpoint (`GET /api/v1/securities`)

No migration. `security` and `daily_close` tables already exist (`app/models/marketdata/`).
`Security.status` is already `active|inactive`; `DailyClose.source` is already `live|simulated` —
this is the exact provenance value the existing `SimulatedBadge` frontend component (unchanged,
reused in Task 8) is built to render, so pass it through unmodified, never re-derive or hardcode it.

**Repository additions** (edit, don't replace, the existing files):
- `app/models/marketdata/security.py` — add `SecurityRepository.list_active(self, *, limit: int,
  after: tuple[str, uuid.UUID] | None) -> list[Security]`: filters `status == SecurityStatus.ACTIVE`,
  orders `ORDER BY symbol, id`, applies a keyset `WHERE (symbol, id) > (after[0], after[1])` when
  `after` is given, fetches `limit + 1` rows (the `+1` is how the service layer knows whether a
  further page exists — do not fetch `limit` and separately guess).
- `app/models/marketdata/daily_close.py` — add `DailyCloseRepository.latest_for_securities(self,
  security_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, DailyClose]`: **one query**, not a loop —
  `SELECT DISTINCT ON (security_id) * FROM daily_close WHERE security_id = ANY(:ids) ORDER BY
  security_id, market_date DESC, recorded_at DESC` (via SQLAlchemy `.distinct(DailyClose.security_id)`
  with matching `.order_by(...)`). **Order `market_date DESC` before `recorded_at DESC`** — a late
  correction to an old date must never be returned as "latest" over a genuinely newer close. Return
  `{}` for an empty `security_ids` input without querying.

**Service** — new `app/services/marketdata/__init__.py` (empty package init — `app/services/marketdata/`
does not exist yet) and `app/services/marketdata/security_catalog_service.py`:
`SecurityCatalogService(uow: MarketDataUnitOfWork)`, method `list_active(self, *, limit: int, after:
str | None) -> tuple[list[tuple[Security, DailyClose | None]], str | None]` — decodes the opaque
cursor via `app/core/pagination.py`'s `decode_cursor`/`encode_cursor` (2-tuple `(symbol, id)`),
calls the two repo methods above (batched, not per-security), zips results, and returns the next
cursor (`None` on the last page) using the same `+1`-row convention `app/controllers/admin/customers.py`
already uses — read that file for the exact pattern before writing this, don't reinvent the pagination
math.

**Controller** — new `app/controllers/api/securities.py`: `securities_bp = Blueprint("securities",
__name__, url_prefix="/api/v1/securities")`, `GET ""`, `@limiter.limit("60 per minute")`, any
authenticated session (customer or staff — a security catalogue is not tenant-scoped, so no
ownership check, just confirm `current_user.is_authenticated`), query param `?limit=&after=`
(`normalize_limit` from `app/core/pagination.py`, default 50 max 200, **rejects** out-of-range —
does not clamp), opens `with MarketDataUnitOfWork(role=<the session's role>) as uow:` (this UoW is
not tenant-scoped — pass `customer_id=None`), calls the service, returns 200.

**View** — new `app/views/securities.py`:
```python
class DailyCloseSummaryResponse(BaseModel):
    price: Price
    market_date: date
    source: str      # "live" | "simulated"
    status: str       # "confirmed" | "stale" | "missing"

class SecurityResponse(BaseModel):
    security_id: uuid.UUID
    symbol: str
    name: str
    asset_class: str  # "equity" | "bond"
    last_close: DailyCloseSummaryResponse | None   # null when the security has never had a close

class SecuritiesListResponse(BaseModel):
    securities: list[SecurityResponse]
    next_cursor: str | None
```

**Register**: import + `app.register_blueprint(securities_bp)` in `app/__init__.py`, in the same
block as the other `api/` blueprints.

**Tests**:
- `tests/integration/test_security_catalog_repositories.py` — `list_active` respects the `status`
  filter and keyset pagination (insert 3 active + 1 inactive security, page with `limit=2`, assert
  the inactive one never appears and the second page picks up exactly where the first left off);
  `latest_for_securities` returns the newest `market_date` (not the newest `recorded_at` of an older
  date) and, separately, a test that a late-arriving correction (`recorded_at` newer, same
  `market_date`) wins over the original row for that date; assert the batched call issues exactly
  one query for N securities (use pytest's query-count fixture if one exists in `tests/conftest.py`,
  otherwise assert via `sqlalchemy.event` query counting — check `tests/integration/` for an existing
  pattern before inventing one).
- `tests/api/test_securities.py` — whole-body-equality assertions per `tests/api/test_profile.py`'s
  style: happy path with a live close, happy path with `last_close: null` (security with no close
  row at all), `source: "simulated"` label passes through untouched, 401 for an anonymous request,
  pagination round-trip (`next_cursor` present mid-list, `null` on the last page), `limit=201` → 422.

**Report:** full `uv run pytest tests/api/test_securities.py
tests/integration/test_security_catalog_repositories.py -v` output, plus a full `uv run pytest`
run confirming nothing else broke, plus `uv run mypy --strict app` and `uv run lint-imports` clean.

---

## Task 3: Backend — Specific-ID tax-lot designation at sell time (FR-20 / ADR-4)

**Read this first, it changes the shape of the task**: the consumption domain logic already exists
and is already tested. `backend/app/services/lots/lot_consumption_service.py`'s
`LotConsumptionService.record_sell_fill(..., designated_lot_ids: Sequence[uuid.UUID] | None = None)`
already fully implements the specific-ID branch via its private `_select_lots_to_consume` — it
validates each named lot belongs to the customer/security (raising `UnknownTaxLotError` otherwise),
sets `lot.designation = LotDesignation.SPECIFIC`, and consumes exactly those lots.
`tests/integration/test_lot_consumption_service.py` already covers this, including the
wrong-customer and nonexistent-lot cases. **Do not modify `lot_consumption_service.py`'s consumption
logic** — it is correct and tested. Confirm this for yourself by reading the file before starting;
if it does not match this description, stop and report `BLOCKED` rather than guessing.

The actual gap: nothing in the request path ever populates `designated_lot_ids`. `POST /orders`
accepts no lot parameter, and fills arrive asynchronously via `trade_update_handler.py`'s webhook
handler with no way to recover what the customer originally asked for.

**3a. Migration.** Add a nullable `designated_lot_ids` column to the `order` table:
`Mapped[list[uuid.UUID] | None] = mapped_column(postgresql.ARRAY(UUID(as_uuid=True)), nullable=True)`
in `app/models/orders/order.py`. `NULL` means FIFO (today's behavior, unchanged for every existing
order). This is a property of the order request itself (same category as `side`/`quantity_requested`),
not a new aggregate — do not create a join table, and do not add a foreign key from `order` to
`tax_lot` (the codebase already deliberately avoids an `order → security` FK for the same boundary
reason; read the existing `order.py` module docstring on this before arguing otherwise in a
self-review). **No new column on `lot_consumption` or `tax_lot`** — `tax_lot.designation` and
`designation_window_closes_at` already record everything needed. Generate the migration with
`uv run alembic revision --autogenerate -m "add order.designated_lot_ids"`, hand-review the
generated file (autogenerate sometimes gets `ARRAY` column defaults wrong — check it explicitly
sets no server default and is nullable), then `uv run alembic upgrade head` to prove it applies.

**3b. `OrderRepository.open_sell_orders`.** Add to `app/models/orders/order.py`'s repository, mirroring
the existing `open_buy_orders()` method exactly (same non-terminal-status filter, same shape) but
filtered to `side == OrderSide.SELL`. This is what lets the netting check in 3c avoid two sequential
sells claiming the same lot.

**3c. New `app/services/orders/lot_designation_service.py`** — `LotDesignationService(uow:
OrdersUnitOfWork)`, method `validate(self, *, customer_id, security_id, side, quantity: Units,
lot_ids: Sequence[uuid.UUID] | None) -> list[uuid.UUID] | None` (returns the validated list, or
`None` unchanged, to be stored on the order):
1. `lot_ids` present and `side != SELL` → raise a new `LotDesignationNotAllowedForBuyError`.
2. `lot_ids == []` (present but empty) → raise a new `EmptyLotDesignationError` — an explicit empty
   list is a client bug, distinct from omitting the field (which means FIFO).
3. `lot_ids` has duplicates → raise a new `DuplicateLotDesignationError`.
4. `len(lot_ids) > 50` → raise a new `TooManyDesignatedLotsError` (OWASP API4, check this before any
   DB round-trip).
5. Every id must resolve to a `TaxLot` matching `(customer_id, security_id)` — reuse
   `TaxLotRepository.lock_by_ids` (already exists) and reuse the existing `UnknownTaxLotError` from
   `lot_consumption_service.py` for a not-found/wrong-owner id — do not invent a second exception
   for the same condition.
6. **Coverage-with-netting**: `sum(lot.quantity_remaining for lot in named_lots) -
   sum(open_sell.quantity_requested - open_sell.filled_quantity for open_sell in
   open_sell_orders(customer_id) if open_sell.designated_lot_ids overlaps named lot ids and
   open_sell.id != this_order) >= quantity`. Else raise a new
   `InsufficientDesignatedLotsError`. **There is no FIFO fallback for an uncovered remainder, at
   placement or at fill time** — a specific-ID designation determines the customer's realized
   gain/loss, and silently substituting FIFO for a shortfall would produce a different tax outcome
   than the one they chose. At fill time, the existing `InsufficientLotsError` (already raised by
   `record_sell_fill`) is correct behavior for a race the netting check narrows but cannot fully
   close — it fails the fill for manual reconciliation, which is what the break queue exists for.

**3d. Wire the controller.** `app/controllers/api/orders.py`'s `CreateOrderRequest` gains
`lot_ids: list[uuid.UUID] | None = None`. In `create_order`, call
`LotDesignationService(uow).validate(...)` before constructing the order, store its return value on
`Order.designated_lot_ids`. Map each new exception to a 422 with a distinct `code`:
`lot_designation_not_allowed_for_buy`, `empty_lot_designation`, `duplicate_lot_id`,
`too_many_designated_lots`, `unknown_tax_lot` (reuse), `insufficient_designated_lots`.

**3e. Fill-time pass-through.** `app/services/orders/trade_update_handler.py`'s sell branch — the
call to `lot_service.record_sell_fill(...)` — add `designated_lot_ids=order.designated_lot_ids`.
One argument. Confirm (read the loop, don't assume) that a partial fill correctly re-reads
`order.designated_lot_ids` on each webhook event and that `TaxLot.quantity_remaining` persisting
between calls makes a repeated designation across multiple partial fills correct with no further
change — if you find it is NOT correct, that's a real finding, report it rather than silently
patching around it.

**3f. Response.** `app/views/orders.py`'s `OrderResponse` gains `designated_lot_ids: list[str] |
None` (stringified UUIDs, matching the existing string-id convention on `LotResponse`).

**Tests:**
- `tests/unit/test_lot_designation_service.py` (new) — one test per validation rule (1-6 above),
  including the netting case: two sell orders naming an overlapping lot, second one rejected;
  and the boundary case where combined `quantity_remaining` exactly equals `quantity` (must pass,
  not fail as a false negative).
- `tests/api/test_orders.py` (edit) — one test per new error code mapped to 422, and a happy-path
  `POST /orders` with `lot_ids` that persists `designated_lot_ids` and is echoed in the response.
- `tests/integration/test_lot_consumption_service.py` — add exactly one new test: two sequential
  partial fills on one sell order, same `designated_lot_ids` passed both times, assert the second
  fill correctly continues consuming from where the first left off (do not touch the existing tests
  in this file — they already cover the base consumption logic).

**Report:** the exact `alembic upgrade head` output proving the migration applies; full
`uv run pytest` output; `uv run mypy --strict app` and `uv run lint-imports` clean; explicitly state
whether 3e's partial-fill re-designation check passed as expected or surfaced a real gap.

---

## Task 4: Backend — Pagination on 5 unbounded customer list endpoints

Reuse `app/core/pagination.py` verbatim — `normalize_limit(limit, default=50, maximum=200)` (rejects
out-of-range, never clamps), `encode_cursor(*values)`/`decode_cursor(cursor)` (opaque, tamper-evident,
max 2048 chars), `paginate(rows, *, limit, cursor_key) -> Page[T]` (`.items`, `.next_cursor`,
`.has_more`). Copy the exact usage pattern from `app/controllers/admin/customers.py::list_customers`
— do not reinvent cursor math. Every change below is purely additive to the response shape
(`next_cursor: str | None` added; every existing field stays); do not remove or rename any existing
field.

| Endpoint | File | Cursor key | Note |
| --- | --- | --- | --- |
| `GET /orders` | `app/controllers/api/orders.py` + `app/models/orders/order.py` | `(created_at, id)` DESC | Today's ordering has no `id` tiebreak — add one, or the cursor is unstable across rows with an identical `created_at` |
| `GET /lots` | `app/controllers/api/lots.py` + `app/models/ledger/tax_lot.py` | `(acquired_at, id)` ASC | Preserve the existing oldest-first order — do not flip to DESC |
| `GET /funding/history` | `app/controllers/api/funding.py` + wherever `FundingHistoryService` reads from | `(effective_date, recorded_at, journal_entry_id)` DESC | Two entries can share both dates; the 3rd key is required for a stable cursor |
| `GET /valuation/history` | `app/controllers/api/valuation.py` + the posting read source | `(effective_date, recorded_at, posting_id)` DESC | The cursor may reference `posting_id`, a field not present in the response body at all — that's fine, the cursor is opaque |
| `GET /statements` | `app/controllers/api/statements.py` + `app/models/restatement/published_snapshot.py` | `(period_start, id)` DESC | Newest period first, matching today's order |

For each: add a `list_for_customer(self, customer_id, *, limit: int, after: tuple | None) ->
list[T]` (or extend the existing list method with `limit`/`after` params if one already exists —
check first, don't create a duplicate method) on the owning repository, fetching `limit + 1` rows
with the keyset `WHERE` clause; add `?limit=&after=` query params to the controller
(`normalize_limit` + `decode_cursor`); add `next_cursor: str | None` to the corresponding response
schema in `app/views/{orders,lots,funding,valuation,statements}.py`.

**This task does not change frontend behavior** — Task 5 does, immediately after, consuming this
exact contract. Do not skip writing the `next_cursor` field correctly because "the frontend isn't
ready yet" — an unpaired backend default-50 change without Task 5 would silently truncate the
current UI to 50 rows, which is why these two tasks are adjacent and both mandatory before Task 5
of the frontend stream (Dashboard, Task 8) ships.

**Tests:**
- `tests/unit/test_pagination_cursor_keys.py` (new) — each of the 5 cursor-key tuples round-trips
  through `encode_cursor`/`decode_cursor` with the correct arity and types.
- Per endpoint, edit `tests/api/test_{orders,lots,funding,valuation_api,statements}.py`: `limit=201`
  → 422; a tampered/malformed cursor → 422; the last page returns `next_cursor: null`; an earlier
  page returns a non-null `next_cursor` that correctly fetches the next page with no duplicate and
  no skipped row.
- Per repository, add an integration test asserting keyset stability: page through with `limit=2`
  across 5 seeded rows, insert a new row that sorts into an already-yielded page's position mid-walk,
  and assert no already-seen row is repeated and no unseen row is skipped.

**Report:** full `uv run pytest` output; confirm all 5 endpoints' existing tests still pass
unmodified in substance (only the new pagination assertions are additions, not rewrites of existing
assertions) unless a specific existing test asserted the old unbounded-list shape, in which case
name exactly which test you had to change and why.

---

## Task 5: Frontend — "Load more" pagination on the 5 corresponding hooks

Consumes Task 4's contract exactly (`next_cursor: str | null` on each list response). Read the
actual `app/views/{orders,lots,funding,valuation,statements}.py` from Task 4's commits before
starting — do not assume the shape, confirm it.

**Decision already made, don't relitigate it**: an explicit **"Load more" button, not infinite
scroll**. The app's real scroll container is non-obvious given the shell's flex-chain layout (see
Global Constraints), a button is trivially testable with Testing Library with no
`IntersectionObserver` mocking, and these are financial ledgers where reaching a definite end
matters.

**Hook shape** — extend the canonical machine from Global Constraints with one more status and one
more action, in each of: `src/features/orders/hooks/useOrders.js`,
`src/features/lots/hooks/useLots.js`, a new `src/features/funding/hooks/useFundingHistory.js`
(split out of the existing `useFunding.js` — `useFunding.js` currently also owns cash-summary
fetching; leave the cash-summary half in place for now, Task 10 finishes that split), a new
`src/features/valuation/hooks/useValuationHistory.js`, and `src/features/statements/hooks/useStatements.js`:
```js
const IDLE = { status: 'idle', items: [], nextCursor: null, error: null }
// status: 'idle' | 'loading' | 'loaded' | 'loading-more' | 'error'
const loadMore = useCallback(async () => {
  if (state.nextCursor === null || state.status === 'loading-more') return
  setState((prev) => ({ ...prev, status: 'loading-more' }))
  try {
    const page = await xApi.list({ after: state.nextCursor })
    setState((prev) => ({ status: 'loaded', items: [...prev.items, ...page.items], nextCursor: page.next_cursor, error: null }))
  } catch (error) {
    setState((prev) => ({ ...prev, status: 'error', error }))
  }
}, [state.nextCursor, state.status])
```
`refetch` keeps its existing meaning unchanged: page 1, full replacement, discards any loaded extra
pages. `hasMore` is derived (`nextCursor !== null`), never stored as a separate boolean.

**UI**: each of the 5 corresponding list components (`OrderList`, `LotTable`, `FundingHistoryTable`,
a to-be-named valuation-history list component, `StatementList`) gets a trailing row/control: a
`Button variant="secondary" size="compact"` reading "Load more" below the list, `disabled` and
showing the existing `Button` `loading` prop while `status === 'loading-more'`, hidden entirely when
`nextCursor === null`. Do this even though `LotsPage`/`OrdersPage`/`FundingPage`/`StatementsPage`
are about to be restyled or deleted in Tasks 8-11 — this proves the hooks and their UI control work
against the real backend before the surrounding chrome changes.

**Tests** (Vitest, using Task 1's harness): for each hook — `loadMore` appends rather than replaces;
`loadMore` is a no-op when `nextCursor === null`; `loadMore` is a no-op while already
`loading-more` (no double-fire on a fast double-click); `refetch` after a `loadMore` resets to page
1, discarding the extra pages; error during `loadMore` surfaces via `ErrorState` without discarding
already-loaded items (only the failed page is lost, not the list). For the "Load more" button
component: renders, click calls `loadMore`, disabled/loading state, absent when no more pages.

**Report:** full `npm test` output, `npm run lint`, `npm run build`; confirm each of the 5 features
was tested against Task 4's actual committed backend (run the backend from this branch locally, not
a mock) at least once by hand or via one integration-style test, not purely unit-tested against a
stubbed `apiClient`.

---

## Task 6: Backend — Real-time push (NFR-18: SSE + Redis Pub/Sub)

Build exactly to `docs/specs/12-production-operations.md` §6: channels `customer:<customer_id>:events`
and `adviser:events`; message shape `{event_type: str, entity_id: str, summary: str}` — a pointer
only, the client re-fetches, it must never trust this payload as authoritative data; publish
strictly **after** the triggering transaction's `uow.commit()`, never inside it (no I/O inside a
transaction, per S0 §5); a dropped/never-open SSE connection is not data loss, since nothing
published over Pub/Sub was ever the sole record of a fact — the next plain `GET` still returns truth.

**6a. Port + adapter layering.** Add to `app/integrations/ports.py`:
```python
class EventBusPort(Protocol):
    def publish(self, channel: str, message: Mapping[str, str]) -> None: ...
    def subscribe(self, *channels: str) -> Iterator[Mapping[str, str]]: ...
```
New `app/integrations/redis/__init__.py` + `app/integrations/redis/event_bus.py` —
`RedisEventBus(redis_url: str)` implementing the port: `publish` JSON-encodes and calls Redis
`PUBLISH`; `subscribe` opens a `pubsub()`, subscribes to the given channels, and yields decoded
messages from `get_message(timeout=...)` in a loop, yielding a heartbeat sentinel (e.g.
`{"event_type": "heartbeat"}`) when `timeout` elapses with nothing received (used by 6c to keep the
HTTP connection alive). New `app/integrations/fake/fake_event_bus.py` — `FakeEventBus` mirroring the
existing `fake_broker.py`'s style (in-memory, records published messages, a test can push a message
and assert `subscribe` yields it).

**Edit `backend/.importlinter`**: add `app.integrations.redis` to the `services-use-ports-only`
contract's `forbidden_modules` list, alongside the existing `app.integrations.alpaca/plaid/stripe/azure`
entries — otherwise this contract silently stops covering the new adapter and `app/services` could
later import it directly without any lint catching it. Run `uv run lint-imports` after this edit to
confirm the contract is syntactically valid and currently passes.

**6b. `app/services/ops/event_publisher.py`** (new) — `EventPublisher(bus: EventBusPort)` is the
only place a channel string or the message shape is constructed. Three methods:
`order_updated(customer_id, order_id, summary)`, `identity_status_changed(customer_id, gate: str,
summary)` (gate is `"kyc"` or `"account_approval"` — the two gates publish independently, never
merged into one event), `break_opened(break_id, summary)` (always publishes to `adviser:events`,
never a customer channel).

**6c. Publish call sites — all strictly after the existing `uow.commit()` at that site:**
1. `app/services/orders/trade_update_handler.py::AlpacaTradeUpdateHandler.handle()` — after the
   `with ... as uow: ... uow.commit()` block exits, call `event_publisher.order_updated(...)` on a
   `fill`/`partial_fill` event and on every terminal non-filled status
   (`TERMINAL_NON_FILLED_STATUSES`, already defined in this file). Inject `EventPublisher` via the
   handler's constructor (mirror how it already receives other collaborators) — do not import
   `RedisEventBus` here; the composition root (wherever this handler is constructed —
   `app/jobs/__init__.py`, confirm the exact line) builds the real bus and passes the publisher in.
2. `app/controllers/webhooks/stripe_identity.py::_apply_verdict` — after each of its two
   `uow.commit()` calls, publish `identity_status_changed` for whichever gate that commit changed.
3. `app/jobs/morning_reconciliation.py` — `ReconciliationService.run_morning_reconciliation()`
   already returns `list[ReconciliationBreak]` (confirmed by reading the code — do **not** modify
   `reconciliation_service.py`). After the job's own commit, iterate the returned breaks and call
   `event_publisher.break_opened(break_row.id, ...)` for each, once per run, not inside
   `reconciliation_service.py`'s per-break loop.

**6d. New SSE endpoints.**
- `app/controllers/api/events.py` — `events_bp`, `GET /api/v1/events/stream`, self-scoped from
  `flask.session["_user_id"]` (no `customer_id` param, same pattern as `profile.py`),
  `@limiter.limit("10 per minute")` (governs connection establishment, not message volume — do not
  rate-limit individual messages), returns `Response(stream_with_context(<generator>),
  mimetype="text/event-stream")`. The generator subscribes to `customer:<id>:events`, yields
  `data: <json>\n\n` per message (same framing style as the existing chat SSE in `chat.py` — read it
  for the exact framing before writing this), yields a `: ping\n\n` comment frame every 20 seconds
  of no real message (proxies reap idle connections otherwise — this is not optional polish), and
  closes cleanly after a hard maximum lifetime of ~30 minutes so `EventSource` on the client
  reconnects rather than holding one worker forever.
- `app/controllers/admin/events.py` — `admin_events_bp`, `GET /api/v1/admin/events/stream`,
  `@requires_role("adviser", "admin")`, subscribes to `adviser:events`, same framing/heartbeat/
  lifetime rules.
- New `app/views/events.py` — `EventMessage` Pydantic schema (`event_type: str, entity_id: str,
  summary: str`) — validate every outgoing frame against it before writing to the stream; the pushed
  event is a contract too, not just an internal detail.
- Register both blueprints in `app/__init__.py`.

**6e. Ops config.** Edit `frontend/nginx.conf.template`: add `proxy_buffering off;` and an adequate
`proxy_read_timeout` (at least the stream's ~30-minute max lifetime) for the `/api/v1/events/stream`
and `/api/v1/admin/events/stream` locations specifically — do not change buffering/timeout for any
other path.

**Tests:**
- `tests/integration/test_event_publisher.py` (new, using `FakeEventBus`) — channel-name and
  message-shape construction for all three publisher methods; publish-after-commit ordering (drive
  a real fill/verdict/break through the actual service with a `FakeEventBus` injected, assert the
  bus received nothing before the commit and exactly one correctly-shaped message after; assert a
  rolled-back transaction publishes nothing at all).
- `tests/api/test_events_stream.py` (new) — 401 for an anonymous request to either stream; a
  customer session can only ever receive messages published to their own `customer:<id>:events`
  channel, never another customer's (drive two sessions, publish to each, assert cross-contamination
  never happens); `@requires_role` enforcement on the admin stream (customer session → 403); a
  heartbeat frame is emitted within the test's configured short timeout (make the heartbeat interval
  test-configurable rather than waiting 20 real seconds in the test).

**Report:** full `uv run pytest` output; `uv run lint-imports` output showing the new contract entry
passes; explicitly confirm you did not modify `reconciliation_service.py`.

---

## Task 7: Frontend — App shell rewrite (5-destination nav, providers, route restructure)

This is the highest-risk frontend task because it is the one place a mistake breaks Chat, which is
explicitly out of scope for change.

**7a. `EventStreamContext`.** New `src/services/eventStream.js` — pure infra (same category as
`apiClient.js`/`mockClient.js`, knows nothing about orders/KYC/breaks): a singleton wrapping
`new EventSource('/api/v1/events/stream')` (or the admin path — parameterize it, since Task 12 needs
the admin variant), a `Map<eventType, Set<listener>>`, `connect()`/`disconnect()`,
`subscribe(eventTypes: string[], listener) -> unsubscribeFn`, exponential-backoff reconnect on the
`EventSource`'s native `onerror` (`EventSource` auto-reconnects on its own by default — add backoff
only for the repeated-immediate-failure case, don't fight the browser's own retry). New
`src/contexts/EventStreamContext.jsx` — `EventStreamProvider({children})` calls `connect()` when
`useSession().status === 'authenticated'` and `disconnect()` on logout or unmount; exposes
`{subscribe, connectionStatus}` via `useEventStream()`.

**7b. `useLiveRefetch` hook.** New `src/hooks/useLiveRefetch.js`:
```js
export function useLiveRefetch(eventTypes, refetch) {
  const { subscribe } = useEventStream()
  useEffect(() => subscribe(eventTypes, refetch), [subscribe, eventTypes, refetch])
}
```
Do not call any hook that uses this yet in this task — Tasks 8-12 add the one-line calls in their
own hooks. This task only builds and tests the primitive itself (subscribe/unsubscribe symmetry: no
listener leak after unmount; a matching event type calls the listener exactly once; a non-matching
event type never calls it).

**7c. Route restructure in `src/App.jsx`.** Five customer destinations replace the current ten
routes: `/dashboard`(from Task 8), `/invest` (Task 9), `/money` (Task 10), `/account` (Task 11),
`/chat` (untouched). Add a redirect from every old path (`/portfolio`, `/orders*`, `/lots`,
`/funding`, `/fees*`, `/statements*`) to its new home so existing bookmarks/links don't 404 — use
`<Navigate replace>` for each. **Critical guard placement, do not get this wrong**: `/onboarding`
stays a **sibling route outside `RequireOnboarded`**, guarded only by `RequireRole
roles={['customer']}` — exactly as today. The new `/account` destination bundles onboarding
*content* (Task 11), but the *route* `/account` sits inside `RequireOnboarded` while a *separate*
`/onboarding` route remains outside it. Nesting `/onboarding` inside `RequireOnboarded` is an
infinite redirect loop: the guard fails closed → redirects to `/onboarding` → still inside the guard
→ fails again. If you are unsure whether a given route is inside or outside `RequireOnboarded`,
trace it explicitly in your own report rather than guessing.

**7d. `AppLayout.jsx`/`AppLayout.css` rewrite.** Five nav links (Dashboard/Invest/Money/Account/Ask
Trueup) replacing the current grouped-links structure. **Keep verbatim** (do not rewrite, just
relocate/reuse as needed): `useDismissablePanel`, `getFocusable`, `initialsFromEmail`,
`AccountMenu`, `NavDrawer`. Mount `<EventStreamProvider>` and `<ThemeProvider>` (from Task 1) here,
wrapping the router's children, inside `SessionProvider`. Add the `ThemeToggle` (Task 1) into the
header's right-hand cluster, next to `AccountMenu`.

**The one property that must survive exactly**, on whichever element now plays the role
`.tu-app-layout__main` plays today: `display:flex; flex-direction:column; flex:1; min-height:0`. Any
new wrapper `<div>` you introduce around `<Outlet/>` must carry these four properties, or the Chat
page's transcript stops scrolling internally and instead the whole page scrolls (see Global
Constraints). **Write one Vitest test** — render the shell, find the main content element, assert
those four computed/inline style properties — specifically so a future change to this file cannot
silently regress Chat without a test failing.

**Report:** full `npm test` output including the new shell layout-contract test; `npm run build`;
manually trace and state in the report which route is inside vs. outside `RequireOnboarded` for
every one of the 5 destinations plus `/onboarding`, `/login`, `/register`.

---

## Task 8: Frontend — Dashboard destination

Depends on Tasks 1, 5, 6 (via 7's plumbing), 7. Read `docs/specs/frontend/design-system.md` for the
full visual spec (palette/type/component rules) — this task is a visual build, follow it exactly
rather than re-deriving a design; the approved mockup already exists as a reference for shape and
copy, ask the controller for its location if not provided in the dispatch.

**Hooks** (new, each following the Global Constraints canonical shape):
- `src/features/portfolio/hooks/useHoldings.js` — `GET /portfolios/holdings`. A 404 with
  `code: "no_model_assigned"` is not an error state — map it to a distinct `status: 'unassigned'`
  (not `'error'`) so the component renders `AssignmentPrompt` (existing component), never
  `ErrorState`, in that case.
- `src/features/portfolio/hooks/usePerformance.js` — `GET /portfolios/performance?range=`, `range`
  param one of `1m|3m|6m|1y|all` (backend's exact enum — confirm casing against
  `app/controllers/api/portfolios.py` before hardcoding).
- `src/features/funding/hooks/useCashSummary.js` — `GET /funding/cash-summary` (split out of the
  existing `useFunding.js`; leave `useFunding.js`'s deposit/withdraw/history responsibilities alone
  for Task 10 to finish restructuring — this task only extracts the cash-summary read).
- `src/features/watchlist/{api/watchlistApi.js,hooks/useWatchlist.js}` (new feature dir) —
  membership persisted to `localStorage` key `trueup.watchlist.v1` (array of `security_id`), every
  read/write wrapped in try/catch so a private-mode/storage-disabled browser renders the empty state
  rather than throwing. Prices come from the real `GET /api/v1/securities` (Task 2) — no mock, no
  simulated PRNG price generator; the `source: "simulated"` field from that endpoint is what drives
  the existing `SimulatedBadge`, shown once in the panel header, not per-row.
- `src/features/securities/{api/securitiesApi.js,hooks/useSecurities.js}` — moves from
  `src/features/portfolio/hooks/useSecurities.js` (delete the old file, update every import) and
  switches from deriving the universe out of `/portfolios/models` target weights to calling
  `GET /api/v1/securities` directly.
- `src/features/valuation/hooks/useValuationHistory.js` — already built in Task 5; this task is
  its first real UI consumer via a ledger band.

**Components** (new):
- `src/components/ValuationChart/{ValuationChart.jsx,.css,index.js}` — hand-rolled SVG line chart,
  no charting library (none exists in `package.json` and one chart doesn't justify adding one).
  `viewBox` scaled to the data, `preserveAspectRatio="none"`, `vector-effect: non-scaling-stroke` on
  the path so it stays crisp at any width. Pointer-move scrub updates a controlled "readout" (the
  hero balance figure becomes a live readout of the scrubbed day, per the approved mockup).
  Keyboard: the chart container is focusable, arrow keys step the scrub cursor one point at a time,
  an `aria-live="polite"` region announces the scrubbed date and value. `role="img"` with an
  `aria-label` summarizing the series. A trailing segment where `is_provisional` is renders visually
  distinct (dashed). Fewer than 2 points renders `EmptyState` inside the plot area, never a broken
  or empty `<svg>`. Load-in animation (a single `stroke-dashoffset` draw, ~700ms) is skipped entirely
  under `prefers-reduced-motion: reduce`.
- `src/components/DriftMeter/{DriftMeter.jsx,.css,index.js}` — a horizontal track, fill to
  `current_weight_pct`, a tick at `target_weight_pct`, the signed drift printed as text (e.g.
  `+1.7pp`), a distinct visual (not just color) treatment when `is_flagged` is true. A holding with
  no target (the CASH line, `security_id: null`) renders a value only, no meter — do not force a
  meter onto a row that has nothing to compare against.
- `src/features/watchlist/components/WatchlistPanel.jsx` (+ `.css`) — add-symbol control sourced
  from `useSecurities`, per-row last price + day-over-day change + a small sparkline (a second,
  smaller instance of the same SVG approach as `ValuationChart`, or a shared sub-component if that's
  cleaner — your call, document which you chose), a remove control per row, one `SimulatedBadge` in
  the panel header (not per-row).
- A ledger band component (name it `LedgerBand` or similar — your call) rendering
  `useValuationHistory`'s paginated entries with an expandable row showing effective-vs-recorded
  date and memo (`docs/specs/frontend/design-system.md`'s bitemporal-visibility intent), plus the
  "Load more" control from Task 5's contract.

**Wire live updates**: `useHoldings`/`useCashSummary`/`useBalance` (existing) each get one added
line — `useLiveRefetch(['order_updated'], refetch)` — since a fill moves both cash and holdings. Do
not build any other live-update mechanism; this is the entire integration surface with Task 6/7's
infra.

**`src/pages/DashboardPage.jsx` (+ `.css`) rewrite** composing all of the above into the approved
layout (hero plate, cash pair at equal visual weight per ADR 5 — same size, same text color, same
treatment for withdrawable and investable, never one visually subordinate to the other — holdings +
watchlist side by side, ledger band below).

**Tests**: component tests for `ValuationChart` (renders N points; scrub emits the correct index on
pointer move and on arrow-key nav; empty/single-point degenerate states render `EmptyState`, not a
broken chart), `DriftMeter` (sign handling, `is_flagged` visual state, no-target CASH case),
`WatchlistPanel` (add/remove round-trips through `localStorage`, renders correctly when
`localStorage` is unavailable), the ledger band (expand/collapse, "Load more"), and `useHoldings`'s
`unassigned` vs `error` vs `loaded` branching.

**Report:** full `npm test` output; `npm run build`; confirm the dashboard renders correctly against
the real backend from Tasks 2/4/6 running locally (not solely against mocked `apiClient` calls in
tests) — describe what you actually ran to verify this.

---

## Task 9: Frontend — Invest destination (portfolio + orders + lots + lot-picker)

Depends on Tasks 3, 5, 7, 8 (reuses `useHoldings`/`DriftMeter` from Task 8 — do not duplicate them).

- Fold `PortfolioPage.jsx` and `LotsPage.jsx`'s content into a new `src/pages/InvestPage.jsx`
  (`+.css`); delete `src/pages/OrdersPage.jsx` (18 lines of pure chrome per the earlier inventory —
  inline its header + "New order" button directly into `InvestPage`, don't preserve it as a
  sub-component with no purpose). `OrderNewPage.jsx`/`OrderDetailPage.jsx` are restyle-only — keep
  their existing hook usage and logic, change only their chrome/wrapper to match the new page.
- `useOrders`/`useOrder` (from Task 5's pagination work) each get one added line:
  `useLiveRefetch(['order_updated'], refetch)`.
- `usePlaceOrder` (existing) gains a `lotIds` param threaded through to the `POST /orders` body's
  `lot_ids` field (Task 3's contract) — only meaningful for `side === 'sell'`.
- New `src/features/orders/components/LotPicker.jsx` (+`.css`) and
  `src/features/orders/hooks/useLotPicker.js` — shown **only** when the order form's side is
  `'sell'`, sourced from `useLots` filtered to the selected security's lots with
  `quantity_remaining > 0`. Shows each candidate lot's `quantity_remaining`, `acquired_at`, and
  current unrealized gain/loss (already on `GET /lots`'s response — do not re-derive it); lets the
  customer select one or more lots; computes and displays the selected total against the requested
  quantity, disabling order submission when the selection under-covers the requested quantity
  (mirroring Task 3's placement-time validation client-side, as a UX nicety — **the server-side
  check in Task 3 remains the actual authority**, do not treat this client check as sufficient on
  its own). Omitting a selection entirely means FIFO — make this the default/undo-able state, not a
  forced choice.
- `OrderResponse.designated_lot_ids` (Task 3) renders on the order detail view — which lots (if any)
  were named for a sell order.
- The existing wash-sale field (`wash_sale_disallowed` on `GET /lots`, already returned by the
  backend today and currently ignored by the UI) gets a visible treatment in the lot table — it is
  always present (Money, `"0.00"` when nothing was disallowed), so render it as a column or inline
  note rather than a conditional badge that only sometimes appears.

**Tests**: `LotPicker` (renders only for sell; selection math; disables submit when short;
FIFO-default/no-selection state); order-detail rendering of `designated_lot_ids`; the wash-sale
column's presence and formatting.

**Report:** full `npm test`, `npm run build`; confirm a real sell order with a lot designation
placed against the Task 3 backend actually round-trips (place it, fetch the order, confirm
`designated_lot_ids` matches what was selected).

---

## Task 10: Frontend — Money destination (funding + fees, bank re-link)

Depends on Tasks 5, 7, 8 (finishes the `useFunding.js` split Task 8 started).

- Fold `FundingPage.jsx` and `FeesPage.jsx` into a new `src/pages/MoneyPage.jsx` (`+.css`).
- Finish splitting `src/features/funding/hooks/useFunding.js`. `useCashSummary` (Task 8) and
  `useFundingHistory` (Task 5 — do not recreate it, it already exists with pagination built in
  against the `/funding/history` contract; this task is simply its first real page consumer) have
  both already been created as separate files. Your job here is only to finish removing
  cash-summary/history reading from the old `useFunding.js` so nothing duplicates them, and to make
  `MoneyPage` consume the two new hooks directly — `useFunding.js` either becomes a thin
  backward-compat re-export or is deleted with every remaining import updated; pick one and do it
  completely, don't leave both the old and new hooks live and half-used.
- `useCurrentBankLink` (existing) — handle the `requires_reauth` status (already modeled
  server-side, per FR-43, and currently never handled client-side): render a distinct interstitial
  ("re-link your bank" prompt) instead of treating it the same as `active`, and **pause** (not
  silently retry or fail) any in-flight deposit/withdraw flow that depends on the link, matching
  FR-43's "never silently fail or retry" requirement exactly.
- Cash pair (withdrawable/investable) at equal visual weight on the Money overview per ADR 5, same
  as Task 8's dashboard treatment — reuse the same presentational component rather than rebuilding
  it twice; if Task 8 didn't already extract one, extract it now and have Task 8's dashboard also
  use it (a small backport, keep it minimal).
- Deposit/withdraw as a segmented control over one form (existing `DepositForm`/`WithdrawForm` logic
  preserved, presentation restyled).

**Tests**: the bank-link component's three states (`active`/`requires_reauth`/no link) including the
paused-flow behavior; the finished `useFundingHistory` hook's "Load more" UI in its real page
context (not just the isolated Task 5 test).

**Report:** full `npm test`, `npm run build`.

---

## Task 11: Frontend — Account destination (profile, both identity gates, statements)

Depends on Tasks 5, 7.

Create a new `src/pages/AccountPage.jsx` (`+.css`) composing profile, both identity gates, bank
link, and statements into one destination — the same fold pattern Task 9 used for Invest and Task
10 used for Money. Delete `src/pages/StatementsPage.jsx` (11 lines of pure chrome per the earlier
inventory — inline `StatementList` directly into `AccountPage`, don't preserve it as a
purposeless wrapper). `src/pages/OnboardingPage.jsx` stays its own component (restyle only, see
below) but is surfaced from within `AccountPage` for an onboarded-in-progress customer, consistent
with Task 7's route trace: the `/account` *route* sits inside `RequireOnboarded`, while the
separate `/onboarding` *route* stays outside it — `AccountPage` itself is only reachable once
onboarded, so it links out to `/onboarding` rather than embedding its steps inline.

- New `src/features/profile/{api/profileApi.js,hooks/useProfile.js,hooks/useUpdateProfile.js,
  components/ProfileForm.jsx}` — **`GET`/`PATCH /profile` has no frontend feature at all today**,
  this is entirely net-new. `PATCH` is partial-update: omitting a field leaves it unchanged, sending
  `null` explicitly clears it — the form must distinguish "user didn't touch this field" from "user
  cleared this field" (e.g. only include a field in the PATCH body if it was actually edited).
  Render `null` values as "Not set", never as a blank/empty-looking field that could be mistaken for
  a loading state.
- `useIdentityStatus` (existing, rewrite) — surface **both** `kyc_status` and
  `account_approval_status` as two independent, separately-labeled indicators (today only one is
  shown) — reference `docs/specs/frontend/design-system.md`'s treatment of this if it specifies one
  before inventing your own. Add `useLiveRefetch(['identity_status_changed'], refetch)`. **Bonus fix
  riding along, do it in this task**: `RequireOnboarded` (in `src/routes/guards.jsx`) currently calls
  `/identity/status` (rate-limited 30/min) on every navigation. Change it to read from
  `SessionContext`'s cached identity status (populated once, refreshed only by the live event above)
  rather than re-fetching on every route change. Confirm `/onboarding`'s reachability is unaffected
  by this change (retest Task 7's guard trace).
- `OnboardingPage.jsx` — restyle only, per the plan; its `kycStepStatus`/`bankStepStatus`
  cooldown-aware logic is correct, keep it; its hardcoded "You're all set" CTA link target must be
  updated from the old `/portfolio` path to the new `/invest` path (Task 9).
- `useStatements` (Task 5's pagination) — first real page consumer. The restated-figure treatment
  (FR-26: both the as-published and as-corrected figures visible, the original struck through and
  labeled, never silently replaced) needs to move from today's separate-view toggle to a
  side-by-side presentation on the statements list itself — check `docs/specs/frontend/design-system.md`
  §8.1 if present for the exact prescribed treatment before designing your own.
- `StatementDetailPage.jsx` — restyle only.

**Tests**: `ProfileForm` (partial-update field-touched tracking, null-clears-field, "Not set"
rendering); the two-gate identity display; the restated-statement side-by-side presentation; the
guard's cached-vs-live-refresh behavior (mock the live event, assert no extra `/identity/status`
call fires on a plain route navigation).

**Report:** full `npm test`, `npm run build`; confirm `/onboarding` is still reachable pre-approval
by tracing the route guard change end-to-end (state exactly what you traced).

---

## Task 12: Frontend — Admin rewiring (mock → real endpoints, live breaks)

Depends on Task 6 (for the live-breaks subscription) and Task 7 (for `eventStream.js`'s admin
variant). Independent of Tasks 8-11 — can run any time after 6/7, included last here only because
it's the lowest-priority remaining task, not because anything blocks it earlier.

- `src/features/admin-customers/api/adminCustomersApi.js` — currently backed entirely by
  `mockClient` despite the real endpoints (`GET /admin/customers`, `GET /admin/customers/<id>`,
  `GET /admin/customers/<id>/fees`, `POST /admin/kyc-overrides/<id>`) already existing and working.
  Rewire every method to `apiClient` against the real paths. `GET /admin/customers` is already
  paginated server-side (per `docs/specs/08-surfaces.md` §4) — give it the same "Load more" hook
  shape as Task 5's other four endpoints rather than inventing a different pagination UI for this
  one. Delete the mock `seed()` factory and its namespace once nothing references it.
- `useBreaks` (existing, admin) gets `useLiveRefetch(['break_opened'], refetch)`, subscribing via
  `eventStream.js`'s admin-stream variant (`/api/v1/admin/events/stream`).
- Confirm `src/services/mockClient.js` itself is **not deleted** — it stays as documented pure
  infra even with its last live consumer gone (per the approved plan's explicit note on this).

**Tests**: `adminCustomersApi.js`'s calls now hit `apiClient` (assert via a mocked `fetch`, not
`mockClient`); `useBreaks`'s live-refetch subscription.

**Report:** full `npm test`, `npm run build`; grep confirmation that `mockClient` has zero remaining
feature-level consumers but the file itself is untouched.

---

## Verification (after all 12 tasks, before finishing the branch)

- `docker compose up -d && cd backend && uv run pytest && uv run mypy --strict app && uv run ruff
  check app tests && uv run lint-imports && uv run alembic upgrade head`.
- `cd frontend && npm run lint && npm run build && npm test`.
- Manual walkthrough: place a sell order with a specific lot designation, confirm the resulting
  lot's `designation` becomes `specific`; open two browser sessions, fill an order in one (or
  trigger the paper-trading webhook manually), confirm the other session's order list updates within
  a couple seconds without a manual refresh; page past 50 rows via "Load more" on orders, lots,
  funding history, valuation history, and statements; kill network mid-SSE-session and confirm
  `EventSource` reconnects on its own; confirm `/onboarding` stays reachable with KYC pending (no
  redirect loop); confirm the Chat page's transcript still scrolls internally, not the whole page;
  toggle the theme through light/dark/system and confirm it persists across a reload.
