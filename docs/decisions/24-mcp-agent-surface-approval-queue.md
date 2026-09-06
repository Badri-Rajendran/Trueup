# 24 — MCP agent surface: read-only tools plus a durable, adviser-approved write queue

## Status

Accepted

## Context

`docs/requirements/non-negotiables.md` #5 requires *"a working MCP surface, not a design for
one"* — minimum three read tools and one write tool that lands in a human approval queue, plus a
written list of operations never handed to an autonomous agent. Nothing satisfies this today.
S11's chat assistant (ADR 18/19) is an HTTP+SSE endpoint that happens to use an LLM internally; it
is not an MCP server, speaks no MCP transport, and has no write path at all — it cannot be
stretched to meet this non-negotiable without becoming a different thing.

This surface exists for a different consumer than S11's: an external MCP client (an operator's own
agent tooling, e.g. Claude Desktop or a custom ops agent), not Trueup's own customer-facing chat.
The two share a security posture — both let an LLM decide what to query against a database holding
real money and PII — but not an implementation: S11's tool runs *inside* Trueup's own request
cycle, authenticated by the caller's existing session; an MCP client is a separate process
connecting over its own transport, with no session cookie to present.

## Decision

### Reuse ADR 19's read boundary; this ADR does not re-derive it

Every read tool executes through the same `trueup_chat_readonly` role and the same eight curated
views (`app/models/chat/curated_views.py`) ADR 19 already built and proved: **the database is the
boundary, not a system prompt** — this ADR's read tools inherit that argument in full rather than
restating it. A read tool is a thin translation from an MCP tool call's arguments to one of these
views' existing `SELECT`s; no read tool executes an LLM-composed query the way S11's `execute_
read_only_sql` does; there is nothing here as flexible as that to bound, since these three tools
have fixed, named shapes (below), not free-text SQL.

### Read tools (minimum three, per the non-negotiable)

1. **`get_portfolio_summary(customer_id)`** — balance, holdings, and assigned model, via
   `v_customer_balance`/`v_holdings` (the same views S11 already curates).
2. **`get_transaction_history(customer_id, since)`** — via `v_transaction_history`.
3. **`list_open_reconciliation_breaks()`** — the aged break queue (S7 §7), adviser-scope only (no
   `customer_id` argument — this tool is inherently cross-tenant, so it authenticates as an
   adviser-equivalent principal, never `trueup_chat_readonly`, which ADR 19 deliberately grants no
   table access outside the eight per-customer curated views).

### Write tools: propose, never execute (all three, per this project's own decision)

An MCP write tool call never touches `order`, `customer.kyc_status`, or `reconciliation_break`
directly. It validates its arguments, then inserts exactly one `agent_action_request` row
(below) with `status = 'pending'` and returns that row's id. Nothing else happens until a human
adviser acts on it through the approval UI (§"Approval flow"). This is the whole answer to "a
write tool that lands in a human approval queue" — there is no code path, tested or
untested, where an MCP tool call itself changes money-moving or compliance state.

1. **`propose_reconciliation_break_resolution(break_id, resolution_note)`**
2. **`propose_kyc_override(customer_id, reason)`**
3. **`propose_rebalance(customer_id)`** — proposes *running* `DriftEvaluationService`'s existing
   evaluation for one customer now, ahead of its monthly schedule; approval executes the same
   `MonthlyRebalanceJob`-owned order-placement path (S9) that already exists, for that one
   customer only. This tool never proposes a specific trade an LLM invented — the trade a human
   approves is whatever the existing, already-tested drift-evaluation logic would itself produce.

### `agent_action_request` (new table, append-only in spirit)

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid, PK | |
| `action` | enum | `resolve_break` \| `kyc_override` \| `rebalance` |
| `arguments` | jsonb | The tool call's own arguments, exactly as received — never re-derived at approval time, so what an adviser reviews is what was actually proposed |
| `requesting_agent` | text | Free-text client identity the MCP transport reports (whatever a client sends as its own name) — an operational label, not an authorization boundary; every write tool call still requires the caller to present a valid adviser/admin credential (below), same as any other privileged action |
| `justification` | text | Required, non-empty — the tool call's own stated reason (e.g. a KYC override's `reason` argument) |
| `status` | enum | `pending` \| `approved` \| `rejected` \| `executed` \| `execution_failed` |
| `reviewed_by` | uuid, FK `staff.id`, nullable | Set on `approved`/`rejected` |
| `reviewed_at` | timestamptz, nullable | |
| `review_note` | text, nullable | The adviser's own note, distinct from the proposal's `justification` |
| `executed_at` | timestamptz, nullable | Set only once the underlying service call actually completes |
| `created_at` | timestamptz | |

Rows are never deleted and never edited outside the single `pending → {approved, rejected}` and
`approved → {executed, execution_failed}` transitions — the same single-transition-guard shape
`kyc_session.resolve()` (S2 §3.2) and `reconciliation_break` already use in this codebase, applied
here for the identical audit reason.

### Approval flow

1. A write tool call inserts a `pending` row (above). The MCP tool's own return value is just the
   row's id and `status: "pending"` — an agent calling this tool never learns whether its proposal
   was good, only that it was recorded.
2. An adviser/admin session lists pending requests via a new `GET /api/v1/admin/agent-requests`
   route (same `@requires_role("adviser", "admin")` shape every other admin route in this codebase
   uses) and approves or rejects one via `POST /api/v1/admin/agent-requests/<id>/approve` /
   `.../reject`, both `@audited` (the same `admin_audit_log` sink every other privileged write in
   this codebase already commits through — an approval is a privileged action in its own right,
   audited identically to resolving a break or overriding KYC directly).
3. **Approval executes; it does not merely flip a status.** `approve` calls the *existing*,
   already-tested service method for that action (`ReconciliationBreakService.resolve`,
   `KycService`'s override path from S8/ADR-24's own §"KYC override" work, or
   `DriftEvaluationService`/the rebalance order-placement path) inside the same transaction that
   marks the row `executed`, using the row's own stored `arguments` — never re-prompting the
   agent, never trusting anything the agent might say between proposal and approval. A failure
   during execution marks the row `execution_failed` with the error recorded, never silently
   `approved`-and-stuck.
4. Rejecting a row is terminal — a rejected proposal is not retried automatically; a new proposal
   is a new tool call and a new row.

### Authentication: a scoped Trueup credential, not the MCP transport's own identity

The MCP server accepts connections authenticated by a long-lived, adviser-scoped API token (a new
`staff_api_token` table: `id`, `staff_id` FK, `token_hash`, `created_at`, `revoked_at`) presented
as an MCP transport-level bearer credential — never a raw database credential, never Trueup's own
session cookie (an MCP client is not a browser). Every read and write tool call resolves the
calling token to a `staff_id`/role exactly as a decorated Flask route resolves `current_user`, and
every write tool call's resulting `agent_action_request.requesting_agent` field additionally
records that resolved identity, not just the client-reported name. A revoked token is rejected
immediately (`revoked_at IS NULL` checked on every call, not just at connection time) — the same
posture ADR 15 already takes toward session invalidation.

### Transport and deployment

The `mcp` package (already a transitive dependency of `openai-agents`, pinned explicitly by this
ADR's implementation since it is now a direct one) runs its own ASGI server
(`MCPServer.run_streamable_http_async`) — a separate process from the WSGI Flask app, the same
"different process, same database, same layered `app/services/`" shape `outbox-worker` (ADR 13)
already establishes for a different reason. Deployed as its own Container App
(`mcp-server`), reusing the backend image with a different entrypoint, exactly as `worker` reuses
it today.

## Consequences

- The non-negotiable is met with no new trust boundary beyond what ADR 19 already proved: reads
  go through the identical curated-view/least-privilege-role perimeter; writes never execute
  without a human in the loop, and when they do execute, they run through the same service code
  every other path into that state change already uses and already tests — there is no
  agent-only code path to a money-moving or compliance state.
- A new attack surface is a new credential type (`staff_api_token`) that must be issued, rotated,
  and revoked carefully — tracked as an operational runbook item, not designed further here.
- Latency: approval is asynchronous by design (a human must act), so no write tool can be used in
  a synchronous, low-latency agent loop — an accepted trade-off, since the entire point is that
  nothing here is autonomous.

## Alternatives considered

- **Let the agent execute directly, audit afterward.** Rejected outright: this is exactly the
  autonomy this non-negotiable exists to prevent, and root `CLAUDE.md`'s LLM Top 10 posture
  ("treat model input and output as untrusted") forbids treating an LLM's tool call as
  self-authorizing for a money-moving or compliance action.
- **A generic "approve any JSON payload" queue**, one row shape for all three actions. Rejected:
  a typed `action` enum with action-specific `arguments` validation at insert time catches a
  malformed proposal before it ever reaches an adviser's queue, rather than surfacing a raw,
  unvalidated JSON blob for a human to interpret under time pressure.
- **Reuse S11's existing OpenAI Agent SDK tool-calling loop as the "MCP surface."** Rejected: it is
  not an MCP server (no MCP transport, no external client can connect to it), and satisfying the
  non-negotiable's literal text ("a working MCP surface") requires an actual MCP protocol
  endpoint, not an internally-similar mechanism under a different name.

## Written list: operations never handed to an autonomous agent (part of this non-negotiable)

- **Moving money or units directly** — no tool executes `DepositService`/`WithdrawalService`/order
  submission itself; `propose_rebalance` only ever proposes running the *existing*, human-designed
  drift-evaluation policy, never a trade amount an LLM invented.
- **Mutating an immutable ledger row** — no tool writes `journal_entry`/`posting` under any
  circumstance; the ledger's append-only invariant (ADR 1) has no agent-facing exception.
- **Publishing or restating a statement** — S6's snapshot/restatement mechanism stays
  system/adviser-triggered only; a wrong statement is a customer-facing legal document, not a
  reversible operational action.
- **Approving its own or another agent's proposal** — approval requires a human adviser/admin
  credential; no service account or agent identity is ever granted the `adviser`/`admin` role this
  approval flow checks.
- **Bypassing KYC/account-approval gates directly** — `propose_kyc_override` only ever creates a
  proposal; only a human's `approve` call can change `customer.kyc_status`.
- **Altering a customer's payment instrument or bank link** — no tool reads or writes
  `payment_method`/`bank_link` at all, read or write; fee-payment and funding instruments are
  entirely outside this surface's scope.
