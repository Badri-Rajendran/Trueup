# S2 — Identity & Funding Rails: Design Spec

Date: 2026-09-04
Status: Draft, pending review
Requirements covered: FR-1–6, FR-39, FR-41–43
Depends on: S1 (ledger — deposits/withdrawals post through `PostingService`; `settlement_obligation`
tracks the ACH T+something gap the same way a trade's T+1 does)
Consumed by: S3 (an order cannot be placed until this spec's KYC + account-approval gates pass),
S8 (customer-facing onboarding/funding screens), S11 (the chat assistant's `v_customer_balance` view
reads S1 accounts this spec funds)

## 1. Purpose

Gate funding and investing on real identity verification (FR-1–3), link exactly one active external
bank account via open banking (FR-4), support deposits and withdrawals through it (FR-5), and handle
the two funding-specific failure modes the brief and gap review named explicitly: a deposit that
bounces after the cash was already invested (FR-6) and a bank re-authentication requirement
mid-flow (FR-43). Two lifecycles gate everything downstream, and they are **distinct, not one**
(FR-39): the identity provider's KYC verdict, and the custodian's own account-approval verdict.

## 2. Non-goals

- Trade placement and the approval-hold mechanism — S3.
- The cash-policy functions (`withdrawable`/`investable`) themselves — S1 §5; this spec only
  produces the `settlement_obligation` rows and journal entries those functions read.
- Multi-bank-account support beyond FR-42's single-active-link model — explicitly out of v1 scope.
- Re-screening an already-approved customer against a later sanctions hit — `requirements.md`'s own
  stated out-of-scope item (gap finding #6).

## 3. Schema

### 3.1 `customer`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | matches the `customer_id` used throughout S1's accounts |
| `email` | text, unique | |
| `password_hash` | text | Argon2id (ADR 15) |
| `kyc_status` | enum | `pending` \| `approved` \| `rejected` (FR-2) — driven by `kyc_session`, never set directly |
| `account_approval_status` | enum | `pending` \| `approved` \| `rejected` — the custodian-side gate (FR-39), independent of `kyc_status` |
| `created_at` | timestamptz | |

**Funding is gated on `kyc_status = approved AND account_approval_status = approved`** — a
conjunction, not an alias for one or the other (FR-39's whole point). `DepositService` and
`WithdrawalService` check both, every time, not once at account creation.

### 3.2 `kyc_session`

Append-only per verification attempt — a resubmission opens a new row, it does not edit the old one
(consistent with the ledger's own append-only posture, applied here for the same audit reason: what
a KYC review actually saw must remain reconstructable).

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `provider_session_id` | text, unique | Stripe Identity's `verification_session` ID — the dedupe key (ADR 9) |
| `status` | enum | `pending` \| `approved` \| `rejected` — mapped from Stripe's session status per ADR 9 |
| `attempt_number` | int | 1-indexed; **default cap: 3 attempts** before the customer's `kyc_status` locks to `rejected` and requires manual adviser override to reopen — a tunable setting (`KYC_MAX_ATTEMPTS`), not a hard architectural number |
| `created_at`, `resolved_at` | timestamptz | |

### 3.3 `bank_link`

| Column | Type | Notes |
| --- | --- | --- |
| `id` | uuid | |
| `customer_id` | uuid, FK | |
| `plaid_item_id` | text, unique | |
| `plaid_access_token` | text, encrypted at rest | never logged, never returned in any API response (root `CLAUDE.md`) |
| `status` | enum | `active` \| `requires_reauth` \| `superseded` (FR-42/43) |
| `linked_at` | timestamptz | |

**FR-42, single active link**: `UNIQUE (customer_id) WHERE status = 'active'` — a partial unique
index, not an application-level check, so the "at most one active link" rule holds even under a
concurrent double-link attempt. Linking a new bank account transitions the prior `active` row to
`superseded` in the same transaction that activates the new one; a `superseded` link's already-
pending obligations are untouched (FR-42's explicit carve-out) — `settlement_obligation` rows key off
`journal_entry_id`, not `bank_link_id`, so nothing about them changes when a link is superseded.

## 4. KYC state machine (ADR 9)

```
Stripe Identity session created (customer starts verification)
  → requires_input / processing   →  kyc_session.status = pending
  → verified                      →  kyc_session.status = approved  → customer.kyc_status = approved
  → canceled                      →  kyc_session.status = rejected
  → requires_input, attempt_number >= KYC_MAX_ATTEMPTS
                                   →  kyc_session.status = rejected → customer.kyc_status = rejected
```

Verdicts arrive as webhooks through the foundation spec's one intake path (`inbound_event`, keyed on
`provider_session_id`) — this spec adds no separate webhook-handling mechanism. `AccountApprovalService`
is a distinct, smaller service: it records the custodian's own account-approval verdict into
`customer.account_approval_status`, never touching `kyc_status`. **Decided (ADR 21): Alpaca Paper
Trading API has no per-customer onboarding verdict to wait on**, so this transition is simulated —
`AccountApprovalService` sets `account_approval_status = approved` automatically once
`kyc_status = approved`, logging a `simulated: true` marker on the audit trail entry so the
distinction from a genuine third-party verdict is never lost.

## 5. Funding flows

### 5.1 Bank linking (Plaid)

`BankLinkService.create_link(customer_id, plaid_public_token)`: exchanges the public token for an
access token (never stored in plaintext — encrypted at rest, per §3.3), creates the `bank_link` row,
supersedes any prior active link in the same transaction (§3.3).

### 5.2 Deposit (FR-5, FR-6)

`DepositService.initiate(customer_id, amount)`:
1. Check `kyc_status`/`account_approval_status` both `approved` (§3.1) and the active `bank_link`'s
   status is `active`, not `requires_reauth` (§5.4).
2. Check the deposit against the tunable per-transaction/per-day caps (default `$25,000`/transaction,
   `$50,000`/day aggregate — gap finding #10's own deferred parameter; **flagged for compliance
   review against actual NACHA/ACH network limits before go-live**, the same treatment ADR 18 gave
   OpenAI's data-retention posture: a defensible engineering default, not a compliance sign-off).
3. Post a `deposit` journal entry (S1's `entry_type`) crediting `cash`, debiting `customer_equity`,
   plus a `settlement_obligation` row (`pending`, `expected_settlement_date` per Plaid's own ACH
   timeline) — cash is available for `investable` purposes per ADR 5's ordering rule immediately,
   before settlement confirms, exactly as any other unsettled inflow.
4. **Bounce handling (FR-6)**: a Plaid webhook reporting an ACH return transitions the
   `settlement_obligation` to `failed` (ADR 2's existing `pending → failed` branch — no new
   mechanism). If the cash was already invested (a buy consumed it before the bounce arrived), the
   failed obligation leaves a **negative** available-cash position — `DepositService` does not try to
   unwind the buy; instead it posts an `entry_type = correction` journal entry establishing a debt
   owed by the customer (a new `customer_receivable` account role, extending S1 §3.1's extensible
   `role` enum), and the customer-facing surface (S8) must show this as an outstanding balance the
   customer needs to cover — collection/write-off policy is explicitly out of scope for this spec,
   consistent with `requirements.md`'s six-week timeline (NFR-11).

### 5.3 Withdrawal (FR-5)

`WithdrawalService.initiate(customer_id, amount)`: checks `amount <= withdrawable(customer)` (S1 §5,
the settled-cash-only policy — never `investable`, per ADR 5's explicit warning that swapping these
two is "a regulatory-grade bug, not a cosmetic one"), and **FR-41**: the destination is always the
currently-`active` `bank_link` — a withdrawal can never target a `superseded` link, structurally,
since the service only ever reads the one row `bank_link`'s partial unique index guarantees exists.

### 5.4 Plaid re-authentication (FR-43)

A Plaid webhook reporting `ITEM_LOGIN_REQUIRED` transitions `bank_link.status → requires_reauth`.
`DepositService`/`WithdrawalService` both check this status (§5.2 step 1) and refuse to proceed with
a clear, actionable error — **never** silently retry against the stale Item (FR-43's explicit
prohibition) and never fail with a generic/opaque error the customer can't act on. The customer
re-links (§5.1), which supersedes the `requires_reauth` row exactly as any other new link would.

## 6. API contract

- `POST /api/v1/identity/kyc-sessions` → starts a Stripe Identity session, returns the client secret
  the frontend needs to render Stripe's hosted verification flow.
- `GET /api/v1/identity/status` → `{ kyc_status, account_approval_status }`.
- `POST /api/v1/funding/bank-links` → exchanges a Plaid public token (§5.1).
- `POST /api/v1/funding/deposits`, `POST /api/v1/funding/withdrawals` → both accept an
  `Idempotency-Key` (NFR-14, per the foundation spec §8's Postgres-backed idempotency store).
- `webhooks/stripe_identity.py`, `webhooks/plaid.py` — through the shared intake path (foundation
  spec §6), no bespoke handling.

All four customer routes require `@login_required` + `@requires_ownership("customer_id")`, per the
foundation spec's standing rule — this spec introduces no new authentication mechanism.

## 7. Edge and corner cases

1. **Concurrent deposit and withdrawal** — both are cash-consuming operations against the same
   `withdrawable`/`investable` policy functions; both acquire the foundation spec's per-customer
   cash-lock (§10.1) before evaluating their check, per that section's generalized rule.
2. **A KYC session approved, then the customer later fails account approval** — funding stays gated
   (§3.1's conjunction) even though `kyc_status = approved`; the customer-facing surface must show
   *which* gate is still pending, not a generic "not approved" message.
3. **A deposit initiated the instant before `bank_link` flips to `requires_reauth`** — the deposit
   already in flight is unaffected (its `settlement_obligation` doesn't depend on the link's current
   status, only its status at initiation); only the *next* deposit attempt is blocked.
4. **A withdrawal requested for more than `withdrawable` but less than `investable`** — rejected
   outright; ADR 5 is explicit that unsettled proceeds are investable but never withdrawable, and this
   spec enforces that at the service boundary, not just documents it.
5. **Idempotent double-submit of a deposit** — the foundation spec's `Idempotency-Key` mechanism
   (§8) replays the original response rather than posting a second `deposit` entry.
6. **A KYC session stuck in `processing` indefinitely** (provider-side delay) — surfaced to the
   customer as `pending`, never silently reinterpreted as `rejected` (ADR 9's explicit warning against
   "a naive 'not yet verified = rejected' simplification").

## 8. Testing strategy

Per the foundation spec's four-layer harness:
- **Unit** — the funding-cap check, the `withdrawable`-vs-`investable` distinction in
  `WithdrawalService`, the bounced-deposit correction-entry construction.
- **Integration** — the partial unique index on `bank_link` actually rejects a concurrent double-link
  (real Postgres constraint, not an application check); the cash-lock serializes a concurrent
  deposit/withdrawal pair correctly.
- **API** — authn/authz/ownership, throttling, the idempotency-replay path, the `requires_reauth`
  rejection path with its specific error code.
- **Contract** — `KycPort`/`BankPort` real (Stripe Identity/Plaid) vs. fake adapters, including a
  fake that simulates `ITEM_LOGIN_REQUIRED` and a bounced ACH return.

## 9. Open parameters (not blocking this spec)

- `KYC_MAX_ATTEMPTS` (default 3) and the deposit/withdrawal caps (default $25,000/$50,000) are
  settings, adjustable without a spec change.
- Manual adviser override to reopen a locked-`rejected` KYC status — an S8/adviser-console action,
  not designed here; this spec only guarantees the underlying state supports it (a new `kyc_session`
  row resets `attempt_number`'s effective count).
- Customer-facing collection/write-off flow for a bounced-deposit debt (§5.2 step 4) — deferred,
  consistent with NFR-11's timeline; this spec guarantees the debt is correctly recorded, not
  resolved.
