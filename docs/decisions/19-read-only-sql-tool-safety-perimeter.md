# 19 — Read-only SQL tool safety perimeter: curated views, least-privilege role, query validator

## Status

Accepted

## Context

FR-49–51 require a chat assistant that can execute LLM-generated `SELECT` queries against a database
holding real money, positions, and PII, scoped to exactly one customer's own data. This is a
fundamentally different trust boundary from every prior sub-project's controls: ADR 15/17's RLS and
role decorators assume the *application* decides what query to run; here, an LLM decides. The core
argument this ADR encodes, stated once because every mechanism below follows from it: **the boundary
that decides what the assistant can access must be the database and a static validator — never the
system prompt.** A prompt is a UX/quality control; it is not a security control, because it can be
bypassed by adversarial input, including input hiding inside the platform's own data (a customer's
free-text memo field, reflected back through a tool result, could contain text that reads as an
instruction — OWASP LLM Top 10's prompt-injection risk, and root `CLAUDE.md`'s "treat model input and
output as untrusted"). Every mechanism below is designed so that a **fully successful** prompt
injection — one that gets the model to *want* to run an arbitrary query — still cannot escalate
privilege, because nothing here trusts the model's intent.

## Decision

### Curated read-model views, not raw ledger tables

`get_database_schema` exposes only a fixed set of purpose-built SQL views, never `posting`,
`journal_entry`, `order_event`, or any other raw table. The bitemporal ledger (ADR 1) and the
as-published/as-corrected split (ADR 6) are subtle enough that a plausible-looking ad hoc query
against raw tables could silently produce a confidently wrong financial answer (e.g. double-counting
a superseded entry) — solving that correctly once, in a view, is far safer than trusting an LLM to
re-derive it on every question. Initial view set, each declared **`WITH (security_invoker = true)`**
— the detail that makes RLS actually apply. Without it, a Postgres view runs with its **owner's**
privileges against the underlying tables, silently bypassing the RLS policies ADR 15/17 already
established; `security_invoker = true` makes the view evaluate under the *calling session's* RLS
context instead, which is what tenant isolation for this feature depends on entirely:

- `v_customer_balance`, `v_holdings`, `v_transaction_history`, `v_realized_gains`, `v_tax_lots`,
  `v_dividends` — direct reporting views over S1/S5's data.
- `v_period_return(as_of)` — ADR 3's TWR, live or as-published depending on `as_of`.
- `v_published_snapshot(period, as_of)` — ADR 6's snapshot-vs-derivation, supporting FR-52's
  "as originally published" answers.

`as_of` defaults to live/now; FR-52 requires any answer tied to a specific period to state explicitly
whether it reflects the live or as-published figure — the same labelling discipline ADR 6 already
requires for return figures generally, now extended to the assistant's own answers.

### A dedicated least-privilege database role

`execute_read_only_sql` runs under a `chat_readonly` database role granted `SELECT` on the curated
views above **only** — no grant on `posting`, `journal_entry`, `bank_link`, `kyc_session`,
`admin_audit_log`, password/credential columns, or any other customer's rows. A query for anything
off this list fails at the database itself, independent of whatever the model was prompted or
manipulated into asking for. This role holds its own database credential, following the same
credential-separation pattern ADR 17 established for `app_bypass` — the chat feature's blast radius
is a different, narrower slice of the schema than either the web API's or the job/worker's role.

### A static query-shape validator, run before any connection opens

Before `execute_read_only_sql` ever opens a database connection, the generated SQL is parsed and
checked: exactly one statement (rejecting multiple statements or a trailing semicolon plus more
SQL), the statement is a `SELECT` (rejecting `INSERT`/`UPDATE`/`DELETE`/`DDL` even though the DB role
already can't perform them — defence in depth means a validator bug and a grant mistake are two
independent failures, not one), and every referenced relation is on the **same allow-list** the
`chat_readonly` role's grants encode — one list, referenced by both the validator and the migration
that grants the role, not two independently-maintained lists that can silently drift apart.

### Statement timeout and row cap, enforced server-side

Every query runs with a Postgres `statement_timeout` (e.g. 3 seconds) and a server-enforced row cap
(e.g. 1,000 rows), applied regardless of what the query itself asks for — protects the production
database from an accidental or adversarial expensive query (a missing filter, an unbounded join)
turning into a performance incident, independent of the validator or the model's behavior.

## Consequences

- FR-50/FR-51 are satisfied structurally: even a successfully-injected instruction telling the model
  to "query all customers" produces, at worst, a query the validator or the database role rejects —
  not a cross-tenant data leak.
- Every new curated view must be added to both the schema-tool's exposed list and the `chat_readonly`
  grant list in the same change, per this ADR's "one shared list" rule — a migration checklist item,
  not a new mechanism.
- Adding a new question category later means adding a new view (and its grant), not touching the
  validator, the role's other grants, or the agent's tool implementations — Open/Closed in practice.
- The required tests (per `docs/specs/11-nl-query-assistant.md`) include a dedicated proof that
  `security_invoker` actually applies: query a curated view as customer A and assert customer B's
  rows are structurally absent, not merely unrequested.

## Alternatives considered

- **Raw tables, schema-scoped, with prompt-only discipline for bitemporal correctness.** Simpler —
  no views to design or maintain. Rejected: correctness would depend on the model consistently
  getting `recorded_at`/`superseded_by` semantics right on every question, exactly the kind of subtle
  mistake that produces a wrong number that looks right — unacceptable for a platform whose hardest-
  graded property is return-figure integrity (NFR-7).
- **Least-privilege DB role alone, no validator.** The database role is the strongest single control
  here, but relying on it alone means a future grant mistake (e.g. an over-broad `GRANT` added
  carelessly to `chat_readonly`) becomes a full bypass with nothing else to catch it. Rejected in
  favor of defence in depth, consistent with ADR 17's refusal to accept RLS as a single point of
  failure for tenant isolation.
- **Validator alone, generic database credentials.** Rejected for the same reason in reverse: a bug
  in the validator (a SQL-parsing edge case it fails to catch) becomes a full bypass if the
  underlying database connection has broad privileges. Neither control alone is acceptable; both
  together mean a single mistake in either layer is not sufficient to cause harm.
