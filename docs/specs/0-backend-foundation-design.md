# S0 — Backend Foundation: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: cross-cutting — NFR-3, NFR-5, NFR-6, NFR-9, NFR-10, NFR-14, and the security
posture required by root `CLAUDE.md` for every FR
Depends on: nothing (this precedes S1)
Consumed by: S1–S10 — every later sub-project is built inside this spine

## 1. Purpose

`requirements.md` decomposes the brief into ten sub-projects and S1 already specifies the ledger
schema in isolation. Nothing yet says how those ten pieces become **one Flask application**: what
layers exist beyond controller/view/model, how an external webhook becomes a ledger posting, what
runs the daily/monthly jobs, how a request is authenticated and authorized, how NFR-3 (units and
money never conflated) is enforced in Python rather than only at the database, and how OWASP/ASVS
controls are structured rather than sprinkled ad hoc.

This spec is the backend's spine. It decides once, for every sub-project, the things that would
otherwise be decided ten times inconsistently: layering, persistence access, event intake, jobs,
security, the API contract, and testing strategy. Sub-project-specific design (S1's schema, S9's
rebalance algorithm, S10's fee state machine) stays in its own spec — this document is deliberately
silent on anything a sub-project spec already owns or will own.

## 2. Non-goals (explicitly out of this spec)

- Any sub-project's internal schema, service logic, or algorithm — those live in `docs/specs/N-*.md`.
- Frontend architecture — `frontend/CLAUDE.md` and a future S8 spec.
- Infrastructure-as-code specifics (exact Azure resource definitions) — an operations concern that
  consumes this spec's job/CLI contract, not a backend design decision.
- Re-deciding anything ADRs 1–12 already settled. Where this spec touches ledger, settlement, or
  restatement concerns, it cites the existing ADR rather than restating it.

## 3. Package layout

MVC as defined in `backend/CLAUDE.md` has no home for domain services (the cash-policy engine, TWR
computation) or provider adapters (Alpaca, Plaid, Stripe). Forcing them into `app/models/` would
make one layer responsible for entities, business rules, and HTTP clients — three different
reasons to change, violating SRP. This spec extends the layer set (recorded as ADR 14) rather than
overload `models/`:

```
backend/app/
├─ core/            depends on nothing else in app/ — the vocabulary every other layer shares
│   money.py           Money | Units | Price value objects + SQLAlchemy TypeDecorators (§4)
│   watermark.py       Watermark: as_published(recorded_at) | live()  (ADR 1, ADR 6)
│   clock.py           MarketClock — America/New_York anchoring, trading-day queries (ADR 12)
│   uow.py             UnitOfWork — the transaction boundary (§5)
│   repository.py      BaseRepository — tenant scoping + append-only guard (§5)
│   errors.py          AppError hierarchy → RFC 9457 problem+json (§8)
│   idempotency.py     client Idempotency-Key store and replay (NFR-14)
│   security.py        @requires_role, @requires_ownership, @audited decorators (§7)
│   crypto.py          Cipher Protocol + EncryptedText TypeDecorator (ADR 23)
│   db.py              DbRole + session-factory registry — inverted so core imports no wiring
│   logging.py         structlog config + per-request correlation ID (§7.4, A09)
│   pagination.py      cursor pagination helpers shared by every list endpoint
├─ models/          SQLAlchemy entities + one repository per aggregate. No business rules here.
│   ledger/            account, journal_entry, posting, settlement_obligation, customer_cash_lock (S1)
│   identity/          customer (S2), staff (this spec, §7.2), kyc_session, bank_link (S2)
│   orders/            order, order_event, approval_hold (S3)
│   marketdata/        security, daily_close, market_calendar_cache, sub_period_return (S4, ADR 12)
│   lots/              tax_lot, lot_consumption, wash_sale_adjustment (S5)
│   reporting/         published_snapshot (S6)
│   recon/             custodian_file_row, reconciliation_break (S7)
│   fees/              fee_accrual, fee_charge, dunning_state (S10)
│   ops/               inbound_event, job_outbox, job_run, admin_audit_log (this spec, §6/§9)
├─ services/        domain + application services — one clear responsibility per class
│   ledger/            PostingService, CashPolicyService (S1)
│   intake/            EventIntakeService — the one path every inbound event enters through (§6)
│   identity/          KycService, AccountApprovalService (S2)
│   funding/           BankLinkService, DepositService, WithdrawalService (S2)
│   orders/            OrderService, ApprovalHoldService, OrderProjectionService (S3)
│   valuation/         ValuationService, TwrService (S4)
│   lots/              LotConsumptionService, WashSaleService, CorporateActionService (S5)
│   restatement/       RestatementService, SnapshotService (S6)
│   recon/             ReconciliationService, BreakAgingService (S7)
│   rebalance/         DriftEvaluationService, RebalanceOrderService (S9)
│   fees/              FeeAccrualService, HighWaterMarkService, FeeChargeService, DunningService (S10)
├─ integrations/    ports + adapters — the only code in the backend that speaks HTTP to a provider
│   ports.py           BrokerPort, BankPort, KycPort, MarketDataPort, PaymentPort, CalendarPort
│   alpaca/            AlpacaBrokerAdapter, AlpacaMarketDataAdapter, AlpacaCalendarAdapter
│   plaid/             PlaidBankAdapter
│   stripe/            StripeKycAdapter, StripeBillingAdapter
│   marketdata/        PolygonAdapter / TwelveDataAdapter (fallback, if used)
│   azure/             KeyVaultCipher — envelope encryption for secret columns (ADR 23)
│   fake/              in-memory adapters for every port — also the FR-33 custodian simulator
├─ controllers/     thin: parse request → authorize → call one service → return a view
│   api/                customer-facing, mounted at /api/v1/*
│   admin/              adviser-facing, mounted at /api/v1/admin/*
│   webhooks/           provider webhook receivers, mounted at /webhooks/*
│   health/             liveness/readiness, unauthenticated
├─ views/           Pydantic response schemas only — an entity is never serialized directly
└─ jobs/            one class per scheduled job, each with a CLI entrypoint (§9)
```

**Dependency rule** (enforced by `import-linter` in CI, per §11):
`controllers → services → models → core`. `services → integrations` only through the `Protocol`s in
`ports.py`, never a concrete adapter import. `models` never imports `services` (a model must not
know about the business rules that use it). `core` imports nothing else under `app/`.

This directly answers the object-oriented / SOLID requirement: controllers depend on service
abstractions (constructor-injected), services depend on repository and port `Protocol`s (DIP), each
class has one reason to change (SRP), new providers or job types extend the system by adding a class
rather than modifying an existing one (OCP), and any adapter is substitutable for its port without
breaking a caller (LSP) — the fake adapters in `integrations/fake/` are the standing proof of this,
since they are used in tests as a drop-in replacement for the real ones.

**Every database enum column is mapped through a Python `enum.Enum`, never read or written as a bare
string in service code** — consistent with §4's reasoning for `Money`/`Units`/`Price`: a typo in a
status string (`"filled"` vs `"Filled"`) is exactly the class of silent bug type safety should turn
into an error at write time, not leave to review. Each entity module owns its enum types alongside
the entity (e.g. `models/orders/order.py` defines `OrderStatus`), and the SQLAlchemy column uses
`Enum(OrderStatus)`, not a raw `String`.

## 4. Typed dimensions (NFR-3, brief line 42: "the classic day-one bug")

S1 §3.3 enforces units-vs-money separation with a database `CHECK` constraint. In Python, both are
otherwise `Decimal` — nothing in the language stops `units + money`. This spec closes that gap with
three immutable value objects in `app/core/money.py`:

```python
class Money:     # NUMERIC(18,4) — USD cents-precision, quantized ROUND_HALF_EVEN at construction
class Units:      # NUMERIC(28,6) — six decimal places per FR-11
class Price:      # NUMERIC(18,6) — per-unit price, not itself a balance
```

Rules:
- Constructed from `str` (or another instance) only — never `float`, which would reintroduce binary
  floating-point error into a regulated ledger. `Money("1500.00")` is valid; `Money(1500.00)` raises.
- `Money + Money → Money`, `Units + Units → Units`. `Money + Units`, `Money * Money`, and
  `Units * Units` all raise `TypeError` — there is no legal operation between two money values via
  multiplication, or between money and units via addition.
- **Two** legal cross-dimension operations, and no others — they are exact algebraic inverses:
  `Price * Units → Money` (FR-11's `value = units × price`) and `Money / Units → Price`, which is
  how S3 §3.1's `order.average_fill_price` is computed from total notional and total units.
  Without the second, S3 would have to unwrap to a bare `Decimal` and re-wrap — reopening exactly
  the hole ADR 16 closes. `Money / Price → Units` is deliberately absent: nothing in S0–S12 needs
  it, and an untested operator on a money path is a liability, not a convenience.
- Comparison (`<`, `==`) is defined only between same-type instances; comparing `Money` to `Units`
  raises `TypeError` rather than silently returning `False`.
- Each type has a SQLAlchemy `TypeDecorator` mapping it to its `NUMERIC` column, so a `Posting.
  amount_money` column is typed `Mapped[Money | None]` — reading a row already returns a `Money`,
  not a bare `Decimal` a caller must remember the meaning of.
- Serialized to JSON as **strings** (`"1500.00"`), never JSON numbers — a JSON number is IEEE-754
  and can silently lose precision in a client. `views/` schemas declare `Money`/`Units` fields
  explicitly so this is enforced at the API boundary too.

This makes NFR-3 a compile-time (`mypy --strict`, CI-gated) and runtime type error, not a
code-review concern — consistent with S1 §3.3's own reasoning that the schema should make mixing a
constraint violation rather than a discipline. Recorded as ADR 16.

## 5. Persistence: repository + unit of work

ADR 6 requires that which bitemporal watermark a read uses "must be enforced at the query layer,
not left to callers to remember." A service holding `db.session` and building its own queries makes
that a convention every call site must remember correctly, forever. This spec puts persistence
behind two abstractions instead:

- **`UnitOfWork`** (`app/core/uow.py`) — the transaction boundary. One instance per HTTP request and
  one per job execution step, holding the SQLAlchemy session and exposing the repositories that
  share it:

  ```python
  with UnitOfWork() as uow:
      uow.ledger.post(entry)          # PostingRepository
      uow.obligations.open(ob)        # SettlementObligationRepository
      uow.commit()                    # exactly one commit point per operation
  ```

  A service method either fully succeeds and commits once, or raises and the whole unit rolls back —
  no service manages its own transaction boundaries.

- **`BaseRepository`** (`app/core/repository.py`), one concrete repository per aggregate:
  - Scopes every query by the current tenant (`g.customer_id`) automatically — the mechanism half of
    tenant isolation (§7.3).
  - Rejects `UPDATE`/`DELETE` at the ORM layer for append-only aggregates (`journal_entry`,
    `posting`, `order_event`, `published_snapshot`), a second guard above the revoked DB grants S1
    §6 already specifies — belt and suspenders on NFR-1. The ledger's money-sum-to-zero invariant
    (S1 §3.4) is additionally enforced by a database-level deferred constraint trigger, since it is a
    cross-row property no `CHECK` constraint can express — see ADR 17. The repository's job is
    writing correct postings; the trigger is the backstop if it doesn't.
  - Every method reading a bitemporally-sensitive aggregate takes `as_of: Watermark` as a
    **required keyword-only parameter** — there is no default. Omitting it is a `TypeError` caught
    by `mypy --strict` before the code ships, not a silently-live figure mislabelled as published.

    ```python
    class LedgerRepository(Protocol):
        def postings_for(self, customer_id: UUID, *, as_of: Watermark) -> Sequence[Posting]: ...
    ```

- **Services depend on repository `Protocol`s, not concrete classes or the session** — Dependency
  Inversion. A test substitutes an in-memory fake repository without touching the service.

- **Rule: no external I/O inside a database transaction.** A service that must call a provider
  (Alpaca, Plaid, Stripe) persists intent plus an outbox row, commits, and only then calls the
  provider from outside the transaction. This prevents a slow or failed provider call from holding a
  ledger transaction open (a lock-contention and data-corruption risk in a regulated ledger) and
  makes every provider call independently retryable through the outbox (§9).

## 6. Event intake — one path for every external signal

`architecture.md` already names this pattern; this spec gives it a concrete shape. Every inbound
signal — broker fills, settlement confirmations, deposit returns, dividends, splits, price
corrections, custodian file rows, daily closes, and KYC verdicts — lands in one table:

```
inbound_event
  id                  uuid
  source              enum   alpaca | plaid | stripe | marketdata | custodian_file
  source_event_id     text   provider's event/execution/fill id
  payload             jsonb  raw, as received
  signature_verified  bool
  received_at         timestamptz
  status              enum   received | processing | processed | failed | unmatched
  attempts            int
  last_error          text, nullable

  UNIQUE (source, source_event_id)
```

**One signal does not arrive over HTTP**: Alpaca order/fill events reach the system over a
`trade_updates` websocket, since the Paper Trading API (ADR 21) has no HTTP webhook events —
[ADR 22](../decisions/22-alpaca-trade-updates-websocket-intake.md). That consumer writes into this
same table, with this same dedupe key and this same outbox hand-off; only its transport differs from
the flow below. Everything else in this section applies to it unchanged.

Flow, identical for every webhook controller in `controllers/webhooks/`:

1. Verify the provider's signature. On failure: respond `401`, log it, **do not** reveal in the
   response whether `source_event_id` was already known (an attacker probing for valid IDs must not
   learn anything from the response shape).
2. Insert into `inbound_event`. The `UNIQUE` constraint **is** the dedupe mechanism (FR-9, NFR-5,
   live-fire scenario 4) — a replayed webhook hits a unique-violation, is caught, and the handler
   returns `200` without reprocessing. This is a single component, not one dedupe implementation per
   handler, exactly as `architecture.md` requires.
3. Enqueue a `job_outbox` row referencing the event and issue `NOTIFY job_outbox_ready` in the same
   transaction, then return `200` immediately. Processing happens asynchronously, drained by the
   always-on outbox worker the `NOTIFY` wakes (§9) — the webhook response must never block on
   downstream ledger work, since a slow response risks the provider's own retry/timeout logic firing
   a duplicate delivery.

Dedupe keys, per the ADRs that already decided them — this spec does not re-decide, only wires them
into one mechanism:
- Alpaca fills: the **execution/fill ID**, never the order ID (ADR 7 — a partial fill produces many
  fills per order).
- Stripe Identity: the `verification_session` ID (ADR 9).
- Stripe Billing: the charge/event ID (ADR 10).
- Plaid: the webhook's own event identity plus `item_id`.
- Market data / custodian file: a vendor- or file-specific per-close or per-row key.

Every payload is parsed through a Pydantic model before any service sees it — **provider data is
untrusted input** (OWASP API10, SSRF/injection via a malformed webhook body), never passed through
to a service as a raw dict.

## 7. Security architecture

Root `CLAUDE.md` mandates OWASP Top 10, ASVS, and API Security Top 10 compliance on every endpoint,
least-privilege roles, CSRF, strict CORS, security headers, secure sessions, hashed passwords, TLS
everywhere, and PII kept out of logs. This section is how those become concrete backend mechanisms
(recorded as ADR 15).

### 7.1 Authentication

**Server-side sessions, not JWTs.** A stolen JWT is valid until it expires; revoking it before then
requires a denylist, which reintroduces exactly the server-side state that choosing JWTs was meant
to avoid — at that point sessions are simpler and no worse. For a platform holding customer money,
the ability to instantly kill a session (a support-escalated compromise, a detected anomaly) matters
more than JWT's statelessness benefit.

- Flask-Login sessions, session state in Redis (the only backend use of Redis — see §9's rejection of
  Redis for financial state).
- Cookies: `HttpOnly`, `Secure`, `SameSite=Strict`. No session token is ever reachable from
  JavaScript, so an XSS bug cannot exfiltrate a live credential.
- CSRF token issued at login, required on every state-changing request (`POST`/`PUT`/`PATCH`/`DELETE`),
  verified before any controller logic runs.
- Passwords hashed with Argon2id (OWASP's current recommendation); session ID regenerated on login
  (session fixation defence).
- Customer sessions: 30-day "remember me" opt-in, 30-minute idle timeout otherwise.
- Revocation: delete the Redis session key — takes effect on the very next request.

### 7.2 Authorization

- **Roles**: `customer`, `adviser`, `admin`. A user has exactly one role for v1 (no role composition
  — YAGNI until a real multi-role need appears).
- **Two tables, not one, since a customer and a staff member are different entities, not the same
  entity with an extra column.** A customer has ledger accounts and a KYC lifecycle (S2 §3.1); an
  adviser/admin has neither — they are internal staff with elevated cross-customer read/write
  access. Confirmed nowhere else in the docs defines where adviser/admin accounts live; resolved
  here rather than left for Wave 2 to invent ad hoc:
  ```
  staff(id, email, password_hash, role, totp_secret_encrypted, created_at)
    role: adviser | admin
  ```
  `customer` (S2 §3.1) is unchanged — no `role` column; its role is always implicitly `'customer'`
  and it never gains a `totp_secret` (MFA is mandatory for staff only, per below). `staff.role` is
  the one place role composition would need to grow past "exactly one," if it ever does.
  `totp_secret_encrypted` uses `EncryptedText` (`app/core/crypto.py`, ADR 23) — ADR 23 already names
  "the adviser TOTP shared secret" as one of its two encrypted columns.
  Both tables satisfy one `AuthPrincipal` `Protocol` (`id`, `email`, `password_hash`, and a `role`
  property — `'customer'` is a constant for `customer` rows, `staff.role` for `staff` rows) so
  Flask-Login's user loader, session serialization, and `@requires_role` operate over one interface
  without needing to know which table a given principal came from. `admin_audit_log.actor_id`
  (below) is deliberately a bare `uuid` with no FK — it must record either a `customer.id` or a
  `staff.id` depending on who acted, and a single FK cannot target two tables.
- `@requires_role(*roles)` — declarative, checked before the controller body runs.
- `@requires_ownership("customer_id")` — for any customer-scoped resource, asserts the path/body
  `customer_id` matches the authenticated principal (a customer) or that the principal is an
  authorized adviser/admin. This is the direct defence against OWASP API1 (Broken Object Level
  Authorization) and API3 (Broken Object Property Level Authorization) — the single most common
  serious defect class in financial APIs.
- **Adviser/admin hardening** — the largest blast radius in the system, since an adviser can reach
  many customers' data:
  - Mandatory TOTP MFA at login, no exceptions in v1.
  - 15-minute idle timeout (versus the customer default of 30).
  - Every privileged action — viewing a customer's ledger, resolving a reconciliation break,
    approving a trade on a customer's behalf — is written to an append-only `admin_audit_log`:
    ```
    admin_audit_log(id, actor_id, action, target_customer_id, payload_hash, recorded_at)
    ```
    Same posture as the ledger itself: no `UPDATE`/`DELETE` grant, `@audited` is a decorator that
    writes the row inside the same `UnitOfWork` as the action it records, so an audit entry and its
    action commit or roll back together — an audited action can never succeed with no audit trail.

### 7.3 Tenant isolation (OWASP A01 — the deferred gap from `requirements.md`'s gap finding #17)

Defence in depth, not a single control:
- **Application layer**: `BaseRepository` scopes every query by `g.customer_id` (§5). Ownership
  decorators reject a mismatched request before it reaches a service.
- **Database layer**: Postgres Row-Level Security on every customer-scoped table, with a
  **role-aware** policy — not a single-customer-only one, since an adviser/admin legitimately needs
  cross-customer reads (FR-31's reconciliation-break screen is a work queue across the whole book,
  not a per-customer lookup):
  ```sql
  ALTER TABLE posting ENABLE ROW LEVEL SECURITY;
  CREATE POLICY tenant_isolation ON posting
    USING (
      current_setting('app.role') IN ('adviser', 'admin')
      OR customer_id = current_setting('app.customer_id')::uuid
    );
  ```
  `posting.customer_id` here is a real column, not `posting`'s own primary key of ownership —
  `posting` rows belong to an `account` (S1 §3.1), which is what actually carries `customer_id`.
  Rather than joining to `account` on every row-security check, S1 §3.3 denormalizes
  `customer_id` onto `posting` itself via a `BEFORE INSERT` trigger that copies it from the
  target account and rejects application code that tries to set it directly — so this policy can
  filter `posting` in one pass, and the denormalized value can never drift from its account.
  The same role-aware shape applies to every other customer-scoped table; only `posting` needed
  the denormalization, since it is the one customer-scoped table whose tenant key lives on a
  different table's row.

  The application sets `SET LOCAL app.role = '<role>'` and `SET LOCAL app.customer_id = '<uuid>'` at
  the start of each `UnitOfWork` transaction. A customer session sets `app.role = 'customer'`, so the
  first branch is always false and the policy behaves exactly as a single-customer filter for them.
  `@requires_role`/`@requires_ownership` (§7.2) remain the actual gate on which routes an adviser can
  reach — RLS is a backstop for *both* shapes of legitimate read, not a switch that turns off for
  adviser traffic. Decided in ADR 17 after a design review found the original single-customer-only
  policy would have silently blocked FR-31's own screen.
- **Bypass is a credential boundary, not a discipline statement.** Jobs and the outbox worker (§9)
  run against a distinct `app_bypass` database role granted `BYPASSRLS`, reached through a **separate
  database credential** (its own connection string, its own Key Vault secret) from the one the web
  API uses. The web API's credential is never granted `BYPASSRLS` — it is structurally incapable of
  bypassing RLS regardless of a future bug in request-handling code, not merely disciplined not to.
- **Why both app-layer and RLS**: a single service that (by mistake, or via a future refactor) builds
  a query outside `BaseRepository` still cannot leak another customer's row, because RLS filters it
  at the database regardless of how the query was constructed. Required tests: (1) disable the
  application guard and assert a cross-customer query under a `customer`-role session still returns
  zero rows — proving the database is the actual control; (2) assert an `adviser`-role session *can*
  read across customers under the same policy — proving the role-aware branch actually works, not
  just the restrictive one.

### 7.4 OWASP Top 10 / ASVS / API Top 10 control map

| Risk | Control |
| --- | --- |
| A01 Broken access control | Sessions + role/ownership decorators + repository scoping + Postgres RLS (§7.2, §7.3) |
| A02 Cryptographic failures | TLS/HSTS via Flask-Talisman; Argon2id password hashing; secrets from Azure Key Vault, never in code or logs |
| A03 Injection | SQLAlchemy parameterized queries exclusively (root `CLAUDE.md`); Pydantic validation on every controller input; no string-built SQL anywhere |
| A04 Insecure design | This spec's threat-modelled sections (§7.3 tenant isolation, §8 error model, §9 job idempotency) |
| A05 Security misconfiguration | Talisman security headers + CSP; `DEBUG=False` enforced outside dev; non-root container user; `SECRET_KEY`/`DATABASE_URL` required with no default — app fails to start rather than run insecurely |
| A06 Vulnerable components | `uv.lock` pinned; `pip-audit` + Dependabot in CI; Trivy image scan gates the Docker build (per root `CLAUDE.md`'s CI/CD section) |
| A07 Identification & auth failures | Argon2id; session regeneration on login; idle + absolute timeouts; mandatory adviser MFA; Flask-Limiter throttles login attempts |
| A08 Software/data integrity failures | Webhook signature verification (§6); append-only ledger (ADR 1); ADR 6's snapshot-vs-derivation cross-check functions as a tamper detector |
| A09 Logging & monitoring failures | Structured JSON logs (structlog) with a correlation ID per request; `admin_audit_log` and `job_run` (§9) as durable audit trails; secrets and PII never logged (root `CLAUDE.md`) |
| A10 SSRF | No user-supplied URL is ever fetched; every provider base URL comes from server-side config, not request input |
| API1 BOLA | `@requires_ownership` on every customer-scoped route; RLS as the backstop |
| API2 Broken auth | Same as A07 |
| API3 BOPLA | `views/` response schemas are explicit allow-lists — an entity is never serialized directly, so a new sensitive column added to a model cannot leak until a view schema is deliberately updated to include it |
| API4 Unrestricted resource consumption | Flask-Limiter (Redis-backed), per-user and per-IP; stricter limits on auth and money-moving routes; `429` with `Retry-After` (root `CLAUDE.md`'s throttling requirement) |
| API5 Broken function-level authz | `/api/v1/*` vs `/api/v1/admin/*` are separate blueprints with independent decorator stacks — an adviser route is never reachable via a customer-authenticated session |
| API8 Security misconfiguration | Same as A05 |
| API10 Unsafe consumption of APIs | Every inbound provider payload validated via Pydantic before use (§6) — provider data is untrusted input |

**LLM Top 10**: recorded as **not applicable to v1** — no AI/LLM feature is in scope for this
platform. Stated explicitly rather than silently omitted, so a future AI feature is understood to
require its own security review against that standard.

## 8. API contract and error model

- Two blueprint groups: `/api/v1/*` (customer) and `/api/v1/admin/*` (adviser/admin), each with its
  own decorator stack (§7.4, API5). `/webhooks/*` for provider callbacks (unauthenticated, signature-
  verified instead). `/health/*` for liveness/readiness, unauthenticated, no business data.
- **Errors are RFC 9457 `application/problem+json`**: `{type, title, status, code, correlation_id}`.
  `code` is a stable machine-readable string (e.g. `insufficient_investable_cash`) a frontend can
  branch on; the response never includes a stack trace, SQL fragment, or internal identifier.
- Request schemas live beside their controller (`controllers/api/orders.py` defines
  `PlaceOrderRequest`); response schemas live in `views/` and are the only thing a controller returns
  — never an ORM entity or a raw dict.
- **Idempotency** (NFR-14): `POST /deposits`, `POST /withdrawals`, and `POST /orders` accept an
  `Idempotency-Key` header. The key, a hash of the request body, and the resulting response are
  stored in a **Postgres** `idempotency_key(customer_id, key, request_hash, response_status,
  response_body, created_at)` table — explicitly not Redis, consistent with §9's rule that Redis
  never holds financial state. The row is written in the same `UnitOfWork` transaction as the
  operation it guards, so the stored response and the operation's effect commit or roll back
  together; an eviction-prone cache is not an acceptable store for something that prevents a
  duplicate deposit or order. A repeated key with a matching body hash replays the stored response; a
  repeated key with a **different** body hash is rejected with `409 Conflict` — silently accepting a
  changed payload under a reused key would be a worse bug than requiring a new key.
- Cursor-based pagination (`app/core/pagination.py`) on every list endpoint (transaction history,
  tax lots, reconciliation breaks) — offset pagination on an append-only, ever-growing ledger
  degrades and can skip or duplicate rows under concurrent inserts.

## 9. Jobs and asynchronous work (ADR 13)

Daily valuation (S4), morning reconciliation (S7), monthly rebalance (S9), daily fee accrual +
monthly charge + dunning retries (S10), and webhook-triggered ledger processing (§6) all need
something to run them — and not all of them have the same latency tolerance. No ADR had decided
this; it is decided here.

**Decision: Azure Container Apps Jobs (cron, defined in IaC) for scheduled batch work, plus one
always-on worker draining a Postgres outbox for hot-path event processing — not Celery with a Redis
broker and Beat scheduler.**

Rationale (full reasoning in ADR 13): a message broker holding in-flight *financial* work is a
second source of truth for "did this event get processed," next to the ledger — the same shape ADR 7
already rejected for order reconciliation ("a duplicated system is not a safer one; it is two things
that can each be wrong"). Redis is not durable by default; an unflushed broker message can be lost on
restart. Celery Beat is a single process with no built-in high availability and no execution history
— if it silently dies, a regulated platform's morning reconciliation simply does not happen with
nothing recording that fact. Azure Container Apps Jobs gives per-execution history, exit codes, and
logs natively, and fits the Azure target already pinned in root `CLAUDE.md`.

Two distinct mechanisms, for two distinct latency needs — conflating them was a design review
finding (ADR 13's "Hot-path draining" subsection has the full rationale):

**Scheduled batch jobs — daily/monthly cadence, Azure cron.**

- **`app/jobs/`** — one class per job (`MorningReconciliationJob`, `DailyValuationJob`,
  `MonthlyRebalanceJob`, `DailyFeeAccrualJob`, `MonthlyFeeChargeJob`, `DunningRetryJob`), each exposed
  as a Flask CLI command (`flask jobs reconcile`). **A job class imports no scheduler** — it is a
  plain, unit-testable class whose `run()` method does the work. This is what makes local dev and CI
  trivial: `make job-reconcile` invokes the identical entrypoint Azure's cron invokes in production,
  so there is exactly one code path to test, not one path for production and a stand-in for
  everywhere else.
- **Production schedule**: Azure Container Apps Jobs, `parallelism: 1`, cron expressions defined in
  infrastructure-as-code (out of this spec's scope — an operations concern consuming this contract).
- **`job_run`** — one row per execution:
  ```
  job_run(id, job_name, cadence, market_date, started_at, completed_at, status, error)
  ```
  `cadence` is `daily`, `monthly`, or `continuous` — this section's own header names both daily and
  monthly batch jobs (`MonthlyRebalanceJob`, `MonthlyFeeChargeJob`), so the cadence enum must cover
  both grains, not just the daily one. Two **partial unique indexes**,
  `UNIQUE (job_name, market_date) WHERE cadence = 'daily'` and
  `UNIQUE (job_name, date_trunc('month', market_date)) WHERE cadence = 'monthly'`, apply to their
  respective cadences — each lets the system **assert** that the expected run for that grain actually
  happened, rather than inferring it from the absence of an alert; a missing expected row is itself a
  detectable condition, the jobs equivalent of NFR-6. `DunningRetryJob` (which legitimately runs
  several times a day) logs `continuous`-cadence rows, which neither uniqueness constraint applies
  to.
- **Concurrency safety**: every batch job acquires `pg_try_advisory_lock(hashtext(job_name))` before
  running and releases it on exit. An Azure retry of a job that is still running, or an overlapping
  manual invocation, no-ops instead of double-executing.
- **Idempotency and resumability**: every job must be safe to run twice and safe to kill mid-run.
  This falls out naturally from the architecture already in place — ledger postings dedupe on
  `source_event_id`, obligations transition once, and jobs re-derive rather than accumulate — but is
  stated here as an explicit, testable requirement rather than an assumed property.

**Hot-path draining — continuous, an always-on worker, not cron.**

- **`job_outbox`** — durable async/retry work (webhook post-processing, Stripe dunning retries):
  ```
  job_outbox(id, task, payload jsonb, attempts, next_attempt_at, status, locked_by, created_at)
  ```
  Drained by one **always-on Container Apps worker revision** (not a scheduled job) using
  `SELECT ... FOR UPDATE SKIP LOCKED` so overlapping wakeups never double-process the same row, with
  exponential backoff between attempts. After a configured maximum attempt count, a row is marked
  `dead_letter` — surfaced as an operational alert, **never** silently dropped (consistent with
  NFR-6's honest-degradation stance applied to jobs, not just market data).
- **Wake mechanism**: the worker blocks on Postgres `LISTEN job_outbox_ready`. The webhook controller
  (§6) issues `NOTIFY job_outbox_ready` in the same transaction as its `job_outbox` insert, so
  draining begins within milliseconds of a fill, KYC verdict, or Stripe event arriving — not on the
  next cron tick. This directly closes the gap between FR-9's "process fills... " intent and a
  cron-only design, without reintroducing a message broker: Postgres is still the only durable store
  for outstanding work, and the worker is a stateless consumer of it, not a queue of its own.
  ADR 13's rejection of Celery (a broker as a second source of truth for financial work) is
  unaffected — this adds one small continuously-running consumer, not a queueing system.
- **Liveness**: a container health check, not a `job_run` row — the correct mechanism for an
  always-on process, distinct from the daily/monthly cadence `job_run` tracks.
- **Redis's role is demoted, not removed**: sessions (§7.1) and Flask-Limiter counters (§7.4) only.
  It never holds financial state, the idempotency store (§8), or queued ledger work.

## 10. Cross-cutting edge and corner cases

Cases specific to one sub-project's domain (wash-sale windows, drift bands, fee dunning states)
belong in that sub-project's own spec. These belong here because they are properties of the
foundation itself and would otherwise be silently assumed away by every sub-project independently:

1. **Concurrent cash-consuming operations racing on the same customer.** S1 §5 defines
   `investable`/`withdrawable` as pure functions with no stated concurrency behavior. This applies to
   every write that debits against one of them, not only order placement — a withdrawal request, an
   order-approval hold, and a monthly fee charge (S10) all read and act on the same policy functions
   through separate service code paths, and any two of them running concurrently could each observe
   "sufficient cash" before either commits. **Resolution**: every cash-consuming operation — order
   hold (S3), withdrawal (S2), fee charge (S10) — evaluates its cash-policy check and writes its
   effect inside one `UnitOfWork` transaction with `SELECT ... FOR UPDATE` on the same canonical
   per-customer cash-lock row, serializing all of them against each other without a global lock. This
   is named explicitly here, once, so no sub-project spec can independently assume the rule applies
   only to its own write path.
2. **Ambiguous order submission.** A network timeout on `POST` to the broker does not tell the
   caller whether the order was actually placed. A deterministic `client_order_id` (derived from
   Trueup's own order ID, never randomly regenerated on retry) makes a retried submission safe at
   the broker; anything still ambiguous is caught the next morning by S7, per ADR 7's explicit
   division of responsibility.
3. **ADR 7's order state machine composing with §5's outbox-mediated provider calls.** ADR 7 defines
   `submitted` as a lifecycle state but was written before this spec's rule that provider calls
   happen outside the database transaction, via the outbox (§5, §9). When S3's own spec is written,
   it must adopt this foundation's pattern explicitly: an order enters `submitted` only once the
   outbox's call to Alpaca actually succeeds, never at the moment intent is persisted — otherwise an
   order could show as `submitted` to a customer while the broker never received it. Recorded here so
   S3 inherits this deliberately; not a defect in either document individually, but a seam between
   them that must be closed when S3's spec is written.
4. **Out-of-order webhook delivery.** A fill event can arrive before its order's accepted event.
   `order_event` folding by `seq` (ADR 7) tolerates gaps and reordering; an event referencing an
   order/entity the system does not yet know about is parked with `status = 'unmatched'` in
   `inbound_event` and surfaced for operator attention rather than silently discarded or blocked.
5. **Webhook signature verification failure.** Respond `401`, log the attempt, and do **not** let
   the response distinguish "bad signature" from "unknown event ID" — either detail helps an
   attacker enumerate valid IDs.
6. **A job killed mid-execution** (container eviction, deploy). The advisory lock releases when the
   connection drops; the next scheduled run detects a stale `started` `job_run` row for the same
   `market_date` and safely resumes or re-runs, per the idempotency requirement in §9.
7. **A job that never fires at all** (scheduler misconfiguration, Azure outage). Detected as a
   missing `job_run` row for an expected trading day — an alertable condition, not something a
   customer discovers first by way of a stale balance.
8. **Daylight saving / market-close boundary.** A stored UTC instant near 4pm ET must never have
   day-boundary logic applied to it directly — every such computation goes through `MarketClock`
   (`app/core/clock.py`, ADR 12), which is the only code in the system allowed to convert a UTC
   instant into "which market day is this."
9. **Decimal precision at every boundary.** Values are quantized to their type's declared precision
   at construction (`Money` to 4 places, `Units` to 6), using `ROUND_HALF_EVEN` (banker's rounding —
   avoids systematic bias from always rounding a half up). A `float` reaching any money- or
   unit-bearing code path is a bug, caught by `mypy --strict` refusing an implicit `float → Money`
   conversion.
10. **Provider outage or slow response.** All outbound provider calls go through `tenacity`-based
    retry with exponential backoff and a circuit breaker; because §5 already forbids provider calls
    inside a database transaction, a provider outage can never leave a half-committed ledger state —
    the worst case is a `job_outbox` row waiting to retry.
11. **Empty or malformed provider payload.** Pydantic validation (§6) rejects it before any service
    sees it; the `inbound_event` row is marked `failed` with `last_error` populated, never processed
    with a null-coalesced default that could misstate an amount as zero.

## 11. Test-driven development harness

Per `backend/CLAUDE.md`'s existing test-first requirement, extended for the layers this spec adds.

- **Real PostgreSQL in every test run — not SQLite.** This design's correctness depends on features
  SQLite does not have: `CHECK` constraints matching Postgres semantics, revoked `UPDATE`/`DELETE`
  grants, Row-Level Security, `NUMERIC` precision matching production exactly, `FOR UPDATE SKIP
  LOCKED`, and advisory locks. A test suite against SQLite would pass while the real invariants go
  unverified — a false sense of coverage worse than no coverage. Schema is created once per test
  session via `alembic upgrade head`; each test runs inside a transaction rolled back on teardown.
- **Test layers**, mirroring the package layout:
  - `tests/unit/` — value objects (`Money`/`Units`/`Price`), cash-policy functions, TWR math: pure,
    no database, fast.
  - `tests/integration/` — repositories, the append-only guard, RLS policies, job idempotency: real
    database required.
  - `tests/api/` — controllers via Flask's test client: request validation, authn/authz, throttling,
    error shape.
  - `tests/contract/` — **the same test suite runs against every port's real adapter and its fake**
    (e.g. `test_broker_port.py` runs once parametrized over `AlpacaBrokerAdapter` and
    `FakeBrokerAdapter`). This is what makes the ports-and-adapters design (§3) pay for itself: a
    fake that silently drifts from the real provider's behavior is caught here, not discovered
    against a live API.
- **Test-first, enforced as a rule**: no production module is created before its failing test
  exists, per root `CLAUDE.md` and `backend/CLAUDE.md`.
- **Fakes are production-quality code**, not throwaway stubs — `integrations/fake/` doubles as
  FR-33's clearly-labelled custodian simulator, so it is built once and used both for automated tests
  and for the live-fire demonstration.
- **CI gates** (feeding the workflows root `CLAUDE.md` requires): `pytest` with a coverage threshold,
  `mypy --strict`, `ruff`, `import-linter` (enforcing §3's dependency rule), an Alembic
  `upgrade head` → `downgrade base` round-trip, `pip-audit`, and a Trivy image scan.

## 12. Configuration, secrets, and migrations

- `pydantic-settings` per environment (`app/config.py`, already named in `backend/CLAUDE.md`); every
  configurable value is read through settings — never `os.environ` inline, never a hard-coded value.
- No secret has a default value in code. A required setting with no value present fails application
  startup immediately, rather than running with an insecure fallback (A05).
- Secrets are sourced from Azure Key Vault in deployed environments and from a local `.env` (never
  committed — root `CLAUDE.md`'s standing rule) in development.
- Every schema-affecting change ships an Alembic migration in the same change that needs it (S1 §8's
  precedent). A migration adding a customer-scoped table must include its `CHECK` constraints,
  revoked grants, and RLS policy in the same revision — these are database-level guarantees and must
  not be left to be added "later" or enforced only by application discipline.

## 13. Sub-project surface map (S1–S10)

Each row states what a sub-project **adds** to the packages in §3 — not a redesign of that
sub-project, which stays owned by its own spec. `—` means the sub-project needs nothing in that
column beyond what this foundation already provides.

| # | Controllers | Services | Models | Jobs | Integrations |
| --- | --- | --- | --- | --- | --- |
| S1 | — (no HTTP surface, per its own spec §2) | `PostingService`, `CashPolicyService` | `account`, `journal_entry`, `posting`, `settlement_obligation`, `customer_cash_lock` | — | — |
| S2 | `api/identity.py`, `api/funding.py`, `webhooks/stripe_identity.py`, `webhooks/plaid.py` | `KycService`, `AccountApprovalService`, `BankLinkService`, `DepositService`, `WithdrawalService` | `customer`, `kyc_session`, `bank_link` | — | `KycPort → Stripe Identity`, `BankPort → Plaid` |
| S3 | `api/orders.py` (fills arrive by websocket, not a webhook — ADR 22) | `OrderService`, `ApprovalHoldService`, `OrderProjectionService` | `order`, `order_event`, `approval_hold` | `AlpacaTradeUpdatesStream` (always-on, ADR 22) | `BrokerPort → Alpaca` |
| S4 | `api/valuation.py` (balance, return, history — FR-18) | `ValuationService`, `TwrService` | `security`, `daily_close`, `market_calendar_cache`, `valuation_run`, `sub_period_return` | `DailyValuationJob` | `MarketDataPort → Alpaca/Polygon`, `CalendarPort → Alpaca` |
| S5 | — (surfaced via S4/S8's read endpoints) | `LotConsumptionService`, `WashSaleService`, `CorporateActionService` | `tax_lot`, `lot_consumption`, `wash_sale_adjustment` | — | — |
| S6 | `api/statements.py` (FR-36 export) | `RestatementService`, `SnapshotService` | `published_snapshot` | (triggered by `DailyValuationJob`'s period-close) | — |
| S7 | `admin/reconciliation.py` | `ReconciliationService`, `BreakAgingService` | `custodian_file_row`, `reconciliation_break` | `MorningReconciliationJob` | custodian file via `integrations/fake/` (FR-33, clearly labelled) |
| S8 | (progressive — reuses S1–S7/S9/S10's read endpoints) | — | — | — | — |
| S9 | `admin/rebalance.py` (visibility only — rebalance itself is system-initiated) | `DriftEvaluationService`, `RebalanceOrderService` | `model_portfolio`, `target_weight` | `MonthlyRebalanceJob` | — (places orders via S3's `OrderService`) |
| S10 | `api/fees.py`, `api/payment_methods.py`, `webhooks/stripe_billing.py` | `FeeAccrualService`, `HighWaterMarkService`, `FeeChargeService`, `DunningService` | `fee_accrual`, `fee_charge`, `dunning_state` | `DailyFeeAccrualJob`, `MonthlyFeeChargeJob`, `DunningRetryJob` | `PaymentPort → Stripe Billing` |

Every FR/NFR in `requirements.md` is covered by exactly one row above via its owning sub-project
(`requirements.md`'s own Sub-Project Decomposition table), or is a cross-cutting NFR this spec
implements directly (NFR-3 §4, NFR-5/NFR-14 §6/§8, NFR-9 throughout, NFR-10 §3's ports-and-adapters
boundary, NFR-13 §10.7's `MarketClock`).

## 14. Open parameters (not blocking this spec, resolved by consuming sub-projects)

- Exact Pydantic request/response schemas per endpoint — each sub-project's own spec.
- Rate-limit thresholds per route class — a security/ops tuning parameter, not an architectural one;
  defaults set conservatively at implementation time and adjustable via settings (§12).
- Whether the adviser console ships as `/api/v1/admin/*` consumed by role-gated routes in the same
  React app, or a separately hostnamed frontend — decided (same app, per-user decision) at the
  frontend level; this spec's blueprint split (`api/` vs `admin/`) is correct either way.
