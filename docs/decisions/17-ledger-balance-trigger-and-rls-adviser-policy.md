# 17 — Database-enforced ledger balance trigger; role-aware RLS for adviser/admin reads

## Status

Accepted

## Context

A review of the backend foundation design (`docs/specs/00-backend-foundation-design.md`) and ADRs
13–16 found two gaps in already-accepted documents, both discovered by tracing a requirement or
invariant through to its actual enforcement mechanism rather than trusting its stated intent:

1. **S1 §3.4's money invariant is a cross-row property with no database enforcement.** "A journal
   entry's money postings sum to zero" spans multiple rows of `posting`. A row-level `CHECK`
   constraint — the mechanism S1 already uses for `posting`'s dimension rule — cannot express a
   cross-row sum. S1 only tests the invariant in application code (`PostingService` plus
   property-based tests). Nothing at the database stops a bug, or a future hand-written script, from
   writing an out-of-balance entry directly into the ledger — the single most consequential gap
   possible in a system whose entire premise is double-entry correctness (NFR-2).
2. **The tenant-isolation RLS policy (ADR 15) is single-customer-shaped, but FR-31 is cross-customer.**
   `USING (customer_id = current_setting('app.customer_id'))` fits a customer's own session, but
   FR-31 requires reconciliation breaks "surfaced on a screen with an aging indicator" — inherently a
   cross-customer work queue for an adviser, not a per-customer lookup. As specified, RLS would
   silently block the very screen FR-31 requires.

Both are enforcement-mechanism gaps in decisions this design already made (ADR 1's balance property,
ADR 15's tenant isolation), not new architectural questions — recorded together here since both are
"close the enforcement gap in an already-accepted decision," and both touch the same object (RLS
policies and constraint triggers live in the same migration layer).

## Decision

### Ledger balance: a deferred constraint trigger, not application discipline alone

```sql
CREATE CONSTRAINT TRIGGER ledger_balance
  AFTER INSERT OR UPDATE OR DELETE ON posting
  DEFERRABLE INITIALLY DEFERRED
  FOR EACH ROW
  EXECUTE FUNCTION check_journal_entry_balance();
```

`check_journal_entry_balance()` sums `amount_money` for the affected `journal_entry_id` (via
`COALESCE(..., 0)`, preserving S1 §3.4's own reasoning that a units-only entry like a split has no
money legs to sum) and raises if the result is non-zero. Being `DEFERRABLE INITIALLY DEFERRED`, it
fires once at `COMMIT`, after every leg of a multi-row posting (e.g. a 4-leg buy) has been written —
not after each individual `INSERT`, so a normal transaction is unaffected and only a genuinely
out-of-balance entry is ever rejected. This makes NFR-2 a database guarantee with the same rigor S1
already applies to the dimension `CHECK` constraint and the revoked `UPDATE`/`DELETE` grants —
closing the one gap in that otherwise-complete guarantee.

### Tenant isolation: a second, role-aware RLS policy for adviser/admin

```sql
CREATE POLICY tenant_isolation ON posting
  USING (
    current_setting('app.role') IN ('adviser', 'admin')
    OR customer_id = current_setting('app.customer_id')::uuid
  );
```

The `UnitOfWork` sets both `app.role` and `app.customer_id` per transaction. A customer session sets
`app.role = 'customer'`, so the first branch is always false and behavior is unchanged from ADR 15's
original design. An adviser/admin session's first branch is true, so RLS permits the row regardless
of `customer_id` — `@requires_role` and `@audited` (ADR 15) remain the actual gate on which routes
and actions an adviser can reach; RLS stays a real, independently-acting backstop for **both** the
single-customer and cross-customer read shapes, rather than being switched off entirely for adviser
traffic (which the alternatives below considered and rejected).

### `app_bypass`'s isolation is a credential boundary, not a discipline statement

ADR 15 stated that the `app_bypass` (BYPASSRLS) role is "used only by job processes" without a
mechanism forcing that. This decision makes it concrete: **the web API and the job/worker processes
hold separate database credentials**, provisioned as distinct connection strings in separate Key
Vault secrets. Only the job/worker credential's underlying database role is granted `BYPASSRLS`. The
web app's credential is structurally incapable of bypassing RLS regardless of any future bug in
request-handling code, because the role it authenticates as was never granted that privilege — a
credential-boundary guarantee, not an "our code doesn't do that" one.

## Consequences

- `docs/specs/01-ledger-units-core-design.md` §6 and §8, and `docs/specs/00-backend-foundation-
  design.md` §5, are updated to reference this trigger as the actual enforcement mechanism for the
  invariant S1 §3.4 already states.
- `docs/decisions/15-session-auth-mfa-tenant-isolation.md`'s tenant-isolation section and
  `docs/specs/00-backend-foundation-design.md` §7.3 are updated with the two-branch policy and the
  `app.role` setting responsibility.
- Every migration adding a customer-scoped table must now include two things, not one: the RLS
  policy from ADR 15, and — where the table represents money movement — verify whether it needs its
  own balance-style trigger or correctly composes with the existing one on `posting`.
- The trigger adds a small, constant per-commit cost (one aggregate query per affected journal entry)
  — accepted, since it runs only at commit and only on the table it protects.

## Alternatives considered

- **Application-layer balance enforcement only (status quo).** Simplest, no new SQL to write or
  maintain. Rejected as the sole guarantee: it holds only as long as every current and future code
  path writing to `posting` is correct, forever, with nothing beneath the application to catch a
  mistake — unacceptable for the ledger of a regulated platform.
- **Application-layer enforcement plus a nightly audit job.** Weaker than a trigger — a bad entry
  could be live and readable for up to a day before detection — but simpler than a PL/pgSQL trigger
  function. Rejected in favor of the trigger: same-transaction rejection is strictly better than
  next-day detection at a modest implementation cost, for the property the brief itself calls
  foundational.
- **Adviser/admin routes reuse the `app_bypass` (BYPASSRLS) role instead of a second policy.** Fewer
  new SQL objects, but means request-handling code sometimes runs with RLS fully off rather than a
  scoped, auditable policy — a materially larger blast radius if an adviser route has an
  authorization bug elsewhere in the stack. Rejected in favor of keeping RLS an active, scoped
  control for all authenticated traffic, with `BYPASSRLS` reserved for non-request job/worker
  processes only.
- **No cross-customer reads in v1; advisers must know/search a specific customer first.** Avoids any
  RLS change, but directly contradicts FR-31's own wording ("breaks surfaced on a screen," implying a
  cross-book work queue) and would require documenting a deviation from an explicit requirement.
  Rejected for the same reason ADR 8 rejected deviating from FR-27's stated cadence without cause.
