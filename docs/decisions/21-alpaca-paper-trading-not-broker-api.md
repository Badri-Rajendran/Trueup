# 21 — Alpaca Paper Trading API, not Broker API; simulated account-approval lifecycle

## Status

Accepted

## Context

Alpaca offers two distinct products. **Broker API** provisions a separate brokerage account per
end-customer, each with its own onboarding/approval verdict from Alpaca — the natural fit for FR-39
("track brokerage-side account approval... as a lifecycle distinct from the identity provider's KYC
verdict"). It requires submitting an application to Alpaca and waiting for approval before sandbox
access is granted. **Paper Trading API** is a single account with instant self-serve API keys and no
approval wait, but no concept of per-customer sub-accounts or an onboarding verdict at all.

S2 §4 already named both paths as options ("an Alpaca Broker API onboarding callback, if the
paper-trading sandbox surfaces one, or a manual/simulated approval otherwise") without choosing
between them. The user has decided (2026-09-04) to use Paper Trading API only, trading Broker API's
per-customer fidelity for zero onboarding delay, given NFR-11's six-week timeline.

## Decision

**Alpaca Paper Trading API** is the broker/custody, market-data, and trading-calendar integration
for v1 (ADR 12 is unaffected — the calendar endpoint is shared across both Alpaca products).

- There is exactly one Alpaca account behind the platform, not one per customer. Trueup's own
  `customer` rows are the only per-customer boundary; Alpaca sees a single pool of orders and
  positions, each tagged with Trueup's `client_order_id` (ADR 7) so fills map back to the owning
  customer — the mapping Trueup already owns, not one Alpaca provides.
- **FR-39's brokerage-side account-approval lifecycle is simulated at the application layer.**
  `AccountApprovalService` (S2 §4) sets `customer.account_approval_status = approved` automatically
  once `kyc_status = approved`, rather than waiting on any Alpaca callback — there is none to wait
  on. This transition is logged with a clear `simulated: true` marker in its audit trail entry, so
  the distinction from a genuine third-party verdict is never lost or misread later as real
  brokerage-side screening.
- **NFR-12 qualification, stated plainly rather than left to read as fully met**: NFR-12 requires
  "brokerage/custody... must be live." Order placement, fills, positions, and market data ARE live
  against Alpaca's real (paper-money) infrastructure — that requirement holds. Only the
  account-approval verdict itself is simulated, because Paper Trading API has no such verdict to be
  live against. `requirements.md`'s NFR-12 row is updated to say so explicitly.

## Consequences

- Zero onboarding wait — API keys are available immediately, consistent with NFR-11's six-week
  build and the T+24h checkpoint (a deposit must already be buying real paper positions).
- Every position, order, and fill in Alpaca is systemwide, not customer-scoped; a bug that reads
  Alpaca state directly instead of through Trueup's own `client_order_id`-keyed projection (S3, ADR
  7) would leak one customer's fills into another's view. This is exactly the discipline ADR 7
  already mandates (fills are ingested by execution ID and projected through Trueup's own ledger,
  never read live from the broker as the source of truth for a customer-facing view) — this ADR adds
  no new mechanism, it raises the cost of ever violating that existing rule.
- If the project later needs genuine per-customer custody fidelity (e.g. a future engagement with
  real money), migrating to Broker API is additive: `BrokerPort` (ADR 14) already abstracts the
  concrete adapter, and `AccountApprovalService`'s simulated branch would be replaced by a real
  webhook-driven one without changing any caller.

## Alternatives considered

- **Alpaca Broker API**, per-customer accounts with a genuine approval verdict. Rejected for v1:
  requires submitting an application and waiting for Alpaca's approval before any sandbox access
  exists at all, an open-ended delay incompatible with NFR-11's fixed six-week window and the
  T+24h-deposit checkpoint. Remains the correct target if the project's scope or timeline changes.
- **Leaving `account_approval_status` permanently `pending`** (never auto-approving). Rejected: FR-3
  hard-gates funding/investing on both KYC and account approval being `approved`; leaving the latter
  permanently unset would block every acceptance scenario in `requirements.md` for no benefit, since
  there is no real verdict being awaited in this product.
