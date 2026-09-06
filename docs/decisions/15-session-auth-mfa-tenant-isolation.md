# 15 — Server-side sessions with CSRF, mandatory adviser MFA, and defence-in-depth tenant isolation

## Status

Accepted

## Context

Root `CLAUDE.md` mandates OWASP Top 10/ASVS compliance, least-privilege roles, CSRF protection,
secure sessions, and hashed passwords, but no ADR had picked a concrete authentication mechanism.
FR-34 (customer surface) and FR-35 (adviser console) imply at least two roles reaching the same
backend, and an adviser role reaches many customers' data — the largest blast radius in the system.
Separately, `requirements.md`'s gap finding #17 explicitly deferred multi-tenant row-level isolation
to "inherited from root `CLAUDE.md`'s generic security stance," which is not a concrete control —
OWASP API1 (Broken Object Level Authorization) is the most common serious defect class in financial
APIs and needs one.

## Decision

### Authentication: server-side sessions, not JWT

Flask-Login sessions backed by Redis. Cookies are `HttpOnly`, `Secure`, `SameSite=Strict`; a CSRF
token is required on every state-changing request. Passwords are hashed with Argon2id; the session
ID is regenerated on login. Customers get a 30-minute idle timeout (30-day "remember me" opt-in).
Revocation is deleting the Redis session key, effective on the next request.

### Adviser/admin hardening

- Mandatory TOTP MFA at login — no exception in v1.
- 15-minute idle timeout (versus 30 for customers).
- Every privileged action is written to an append-only `admin_audit_log(actor_id, action,
  target_customer_id, payload_hash, recorded_at)` inside the same transaction as the action itself,
  via an `@audited` decorator — an audited action cannot commit without its audit row also
  committing.

### Authorization: role + ownership decorators

Three roles for v1 — `customer`, `adviser`, `admin` — one per user, no composition. `@requires_role`
gates by role; `@requires_ownership("customer_id")` asserts a customer-scoped resource belongs to
the authenticated principal or an authorized adviser/admin. `/api/v1/*` (customer) and
`/api/v1/admin/*` (adviser) are separate Flask blueprints with independent decorator stacks, so an
adviser-only route is not reachable via a customer session regardless of application logic elsewhere
(OWASP API5).

### Tenant isolation: application guard and Postgres RLS together

- **Application layer**: `BaseRepository` (ADR 14) scopes every query by the session's
  `customer_id`; ownership decorators reject a mismatch before a service runs.
- **Database layer**: Row-Level Security on every customer-scoped table, with a **role-aware**
  policy — `USING (current_setting('app.role') IN ('adviser','admin') OR customer_id =
  current_setting('app.customer_id')::uuid)` — not a single-customer-only policy. The application
  issues `SET LOCAL app.role = '<role>'` and `SET LOCAL app.customer_id = '<uuid>'` at the start of
  each transaction; a customer session sets `app.role = 'customer'`, so the first branch is always
  false and the customer sees only their own rows. An adviser/admin session's first branch is true,
  so RLS permits cross-customer reads — required for FR-31's reconciliation-break screen and any
  other adviser work-queue view, which are inherently cross-customer, not per-customer lookups.
  `@requires_role` and `@audited` remain the gate on which routes and actions an adviser can reach;
  RLS stays a real, active, scoped backstop for adviser traffic rather than being switched off for
  it. Corrected by ADR 17 after a design review found the original single-customer-only policy would
  have silently blocked FR-31's own screen.
- **`app_bypass`'s isolation is a credential boundary, not a discipline statement.** The web API and
  job/worker processes hold **separate database credentials** (distinct connection strings in
  separate Key Vault secrets) from application startup. Only the job/worker credential's underlying
  database role is granted `BYPASSRLS`; the web app's credential is structurally incapable of
  bypassing RLS regardless of any future bug in request-handling code, because the role it
  authenticates as was never granted that privilege. Corrected by ADR 17 after "never used by
  request-handling code" was found to be a policy statement with no mechanism enforcing it.
- Required test: disable the application-layer guard and confirm a cross-customer query still
  returns zero rows for a `customer`-role session — proving the database is a real, independent
  control, not a second copy of the same one — and separately confirm an `adviser`-role session
  *can* read across customers under the same RLS policy.

## Consequences

- `backend/CLAUDE.md` and `docs/specs/00-backend-foundation-design.md` §7 carry the concrete
  mechanism; `requirements.md`'s gap finding #17 deferral for tenant isolation is resolved by this
  ADR rather than staying open.
- Connection setup for every request/job step must issue `SET LOCAL app.role` and
  `SET LOCAL app.customer_id` — a real, ongoing discipline requirement, mitigated by putting both
  inside `UnitOfWork.__enter__` (ADR 14) so no call site can forget them.
- A single service that (by mistake or future refactor) builds a query outside `BaseRepository`
  still cannot leak another customer's row, because RLS filters it at the database regardless of how
  the query was constructed.
- Building and testing MFA and the audit log adds real implementation time against NFR-11's
  six-week budget — accepted, since the adviser role's blast radius (many customers' financial data
  behind one password) makes this the highest-risk access path in the system.

## Alternatives considered

- **JWT access + refresh tokens.** Stateless and trivially horizontally scalable, with no CSRF
  surface — but revoking a compromised token before its natural expiry requires a server-side
  denylist, reintroducing exactly the state that choosing a stateless mechanism was meant to avoid.
  For a platform holding customer money, instant revocation on a detected compromise matters more
  than JWT's scaling benefit at this stage. Rejected.
- **Adviser access with MFA, audit log, and an IP allow-list.** Strongest posture considered, but an
  allow-list needs a real, maintained source of truth and risks locking out a legitimate adviser
  working from a new location before there is an operational process to update it. Rejected for v1
  as disproportionate operational friction; revisitable once there are real advisers and a support
  process to maintain the list.
- **Audit log only, MFA deferred to v1.1.** Cheaper against the six-week timeline, but leaves a
  single stolen adviser password sufficient to reach every customer's financial data with no second
  factor standing in the way. Rejected as an unacceptable residual risk for the role with the
  largest blast radius in the system.
- **Application-layer tenant scoping only, no RLS.** Simpler operationally — no `SET LOCAL`, no
  bypass role to manage. Rejected: a single raw query built outside the base repository (a plausible
  mistake in a codebase ten sub-projects will extend) leaks silently, with nothing beneath the
  application layer to catch it.
- **Postgres RLS only, no application-layer guard.** Impossible to bypass from application code and
  a single point to audit — but a misconfigured `BYPASSRLS` grant would then be the *only* control,
  and its failure would be invisible until exploited. Rejected in favor of defence in depth.
