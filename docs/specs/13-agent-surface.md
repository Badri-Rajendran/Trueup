# S13 — MCP Agent Surface: Design Spec

Date: 2026-09-06
Status: Draft, pending review
Requirements covered: `docs/requirements/non-negotiables.md` #5 (this spec's own requirement —
no FR/NFR in `requirements.md` names it, since the non-negotiables predate and sit outside that
catalogue)
Depends on: S0 (foundation — layering, `UnitOfWork`, `@audited`/`@requires_role`, RLS), S7
(reconciliation breaks), S2 (KYC), S9 (rebalancing), ADR 17 (RLS), ADR 19 (curated-view read
boundary — this spec's read tools reuse it directly rather than re-deriving it)
Consumed by: nothing — this is an external-facing operational surface, not depended on by any
other sub-project
Decision record: `docs/decisions/24-mcp-agent-surface-approval-queue.md` — read that first; it
carries the *why* for every mechanism this document only specifies the *how* of.

## 1. Purpose

Build a real MCP (Model Context Protocol) server an external agent client can connect to, exposing
three read tools and three write tools, where every write is a proposal landing in a durable,
adviser-approved queue rather than an executed action. ADR 24 is the full rationale; this spec is
the concrete schema, routes, and module layout an implementer builds from.

## 2. Non-goals

- A second natural-language interface competing with S11's chat assistant — this surface has no
  conversational UI of its own; it is a protocol endpoint for an external MCP client.
- Any new business logic — every write tool's *approved* execution calls an existing, already-
  tested service method (S7's break resolution, S2/S8's KYC override, S9's drift evaluation +
  order placement). This spec adds no new financial logic, only the proposal/approval scaffolding
  around calling what already exists.
- Autonomous execution of any kind — see ADR 24's "written list" section, reproduced nowhere else;
  that list is normative.

## 3. Schema

### 3.1 `agent_action_request`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid, PK, default `gen_random_uuid()` | |
| `action` | enum `agent_action_type`: `resolve_break` \| `kyc_override` \| `rebalance` | |
| `arguments` | jsonb, not null | Exactly the tool call's own arguments (§4.2 per-tool shapes) |
| `requesting_agent` | text, not null | The resolved `staff_api_token` identity's own label (§3.2), not a client-reported string |
| `justification` | text, not null, `CHECK (length(justification) > 0)` | |
| `status` | enum `agent_action_status`: `pending` \| `approved` \| `rejected` \| `executed` \| `execution_failed`, default `pending` | |
| `reviewed_by` | uuid, FK `staff.id`, nullable | |
| `reviewed_at` | timestamptz, nullable | |
| `review_note` | text, nullable | |
| `execution_error` | text, nullable | Set only alongside `execution_failed` |
| `executed_at` | timestamptz, nullable | |
| `created_at` | timestamptz, not null, `server_default=now()` | |

Constraints (mirroring `reconciliation_break`'s own `resolved_break_requires_resolver` pattern):

- `CHECK ((status NOT IN ('approved','rejected')) OR (reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL))`
- `CHECK ((status <> 'executed') OR (executed_at IS NOT NULL))`
- `CHECK ((status <> 'execution_failed') OR (execution_error IS NOT NULL))`
- No RLS tenant-isolation policy: this table has no single owning customer (some rows reference
  one via `arguments->>'customer_id'`, but the row itself is adviser/admin-scoped, matching
  `reconciliation_break`'s own nullable-`customer_id` precedent) — access control is
  `@requires_role("adviser", "admin")` on every route, the same as `admin_breaks`.
- `REVOKE UPDATE, DELETE` from `trueup_app` is **not** applied here (unlike ledger tables) — the
  single-transition status updates above are legitimate application writes, not ledger mutation;
  `trueup_app` still cannot `DELETE` (append-only in spirit, per ADR 24).

### 3.2 `staff_api_token`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid, PK | |
| `staff_id` | uuid, FK `staff.id`, not null | |
| `label` | text, not null | Human-readable, e.g. "ops laptop MCP client" — shown in the token-management UI, never the raw token |
| `token_hash` | text, not null, unique | SHA-256 of the raw token; the raw value is shown exactly once, at creation, never stored or logged (same handling discipline as a password) |
| `created_at` | timestamptz, not null | |
| `revoked_at` | timestamptz, nullable | |

Issuing a token is itself `@audited`; a new `POST /api/v1/admin/staff-api-tokens` route
(adviser/admin, self-service for one's own `staff_id` — an adviser issues a token for themselves,
never for another staff member) returns the raw token once. `DELETE
/api/v1/admin/staff-api-tokens/<id>` sets `revoked_at`.

## 4. MCP server

### 4.1 Module layout

```
app/mcp/
  __init__.py        # MCPServer construction, tool registration
  auth.py            # staff_api_token bearer resolution -> (staff_id, role)
  read_tools.py       # the 3 read tools, each a thin call into ADR 19's curated views
  write_tools.py       # the 3 write tools, each validating args then inserting one row
  entrypoint.py        # run_streamable_http_async() wiring, the process's own main()
```

Follows the layering rule (`app/mcp/` sits alongside `app/controllers/` — both are entry-point
layers calling into `app/services/`, never the reverse); `import-linter` gets a new contract
mirroring the existing `controllers -> services` one, extended to `app.mcp -> app.services`.

### 4.2 Tool contracts

**Read tools** (bearer token resolves to a `staff_id`; `trueup_chat_readonly`-equivalent DB access
for the two customer-scoped tools, ADR 19's own role for `list_open_reconciliation_breaks`):

- `get_portfolio_summary(customer_id: str) -> {balance, holdings, assigned_model}`
- `get_transaction_history(customer_id: str, since: str | None) -> {transactions: [...]}`
- `list_open_reconciliation_breaks() -> {breaks: [...]}` (adviser-scope; no `customer_id` arg)

**Write tools** — each validates its own arguments (a malformed `customer_id`/`break_id` is
rejected at the tool-call boundary, before any row exists — never accepted into the queue as
"pending" only to fail review), then does exactly:
```python
request_id = uow.agent_action_requests.create(
    action=..., arguments={...}, requesting_agent=staff_label, justification=justification,
)
uow.commit()
return {"request_id": str(request_id), "status": "pending"}
```

- `propose_reconciliation_break_resolution(break_id: str, resolution_note: str) -> {request_id, status}`
- `propose_kyc_override(customer_id: str, reason: str) -> {request_id, status}`
- `propose_rebalance(customer_id: str) -> {request_id, status}`

## 5. Approval API (`app/controllers/admin/agent_requests.py`)

| Route | Method | Notes |
| --- | --- | --- |
| `/api/v1/admin/agent-requests` | GET | List, filterable by `status` (default `pending`), paginated (`app/core/pagination.py`) |
| `/api/v1/admin/agent-requests/<id>` | GET | One request's full detail |
| `/api/v1/admin/agent-requests/<id>/approve` | POST | `@audited`; body: `{review_note: str | None}`; executes the underlying service call in the same transaction, sets `executed`/`execution_failed` |
| `/api/v1/admin/agent-requests/<id>/reject` | POST | `@audited`; body: `{review_note: str}` (required — a rejection needs a stated reason) |

All four `@requires_role("adviser", "admin")`, same shape as `app/controllers/admin/rebalance.py`.

### 5.1 Execution mapping (approve only)

| `action` | Calls |
| --- | --- |
| `resolve_break` | The same service `POST /admin/breaks/<id>/resolve` already calls, with `arguments.resolution_note` |
| `kyc_override` | The same service `POST /admin/kyc-overrides/<customer_id>` calls (S8/Phase 2), with `arguments.reason` becoming the override's own reason |
| `rebalance` | `DriftEvaluationService.evaluate` + the same order-placement path `MonthlyRebalanceJob` uses, for `arguments.customer_id` only |

## 6. Edge and corner cases

1. **A proposal references an entity that no longer exists by approval time** (a break already
   resolved by someone else, a customer since deleted — customers are never hard-deleted in this
   system, so realistically "already resolved") — the execution call's own existing not-found/
   already-resolved error surfaces as `execution_failed` with that error recorded, never a silent
   no-op and never a crash.
2. **Two advisers approve the same request concurrently** — `approve`/`reject` both take a row
   lock (`SELECT ... FOR UPDATE`, matching `OrderRepository.get_for_update`'s precedent) and the
   `pending -> {approved,rejected}` single-transition `CHECK` makes the second call fail cleanly
   (`ValidationError`/409, not a double-execution).
3. **A revoked `staff_api_token` is used mid-session** — every tool call re-checks
   `revoked_at IS NULL`, not just at MCP connection time (ADR 24).

## 7. Testing strategy

- Unit: `agent_action_request`'s status-transition guard (mirrors `reconciliation_break`'s own
  transition tests); each write tool's argument validation.
- Integration: the row-lock/concurrent-approval race (edge case 2); RLS/role behavior for
  `list_open_reconciliation_breaks` under a non-adviser token.
- API: the four approval routes — happy path, validation errors, authn/authz, the execution-
  mapping table's three rows actually calling through to their real service and changing real
  state (not mocked), execution failure recorded correctly.
- Contract-style: a minimal MCP client (the `mcp` package ships a client for exactly this) calling
  each of the six tools end-to-end against a running `app.mcp` server in a test — the one place
  this spec's own transport actually gets exercised, not just the service calls underneath it.

## 8. Open parameters (not blocking this spec)

- Token rotation cadence and a bulk-revoke-on-offboarding runbook — operational policy, not a
  schema or code concern this spec resolves.
- Whether `list_open_reconciliation_breaks` needs its own pagination for a very large break queue
  — deferred until real volume argues for it, consistent with S12 §2's own "add a new migration
  when a real pattern demands it" posture.
