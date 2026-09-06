# 9 — Stripe Identity as the decided KYC provider

## Status

Accepted

## Context

FR-1–3 require a real third-party KYC check with three surfaced states (pending/approved/rejected)
gating funding and investing. The brief names three interchangeable sandbox options for this row —
Persona, Sumsub, Stripe Identity test mode — without picking one; `requirements.md` left the choice
open. The user separately decided (2026-09-04) that Stripe should be Trueup's payment-gateway
vendor for fee collection (ADR 10). This ADR settles the KYC provider choice.

## Decision

**Stripe Identity** is the decided KYC provider for v1, chosen from the brief's own pre-approved
list — this is a vendor pick, not new architecture.

- Verification verdicts arrive via Stripe webhook events on the `identity.verification_session`
  object and are ingested through the same idempotent event-intake path as every other external
  signal (architecture.md, ADR 7's dedupe pattern), keyed on the `verification_session` ID.
- FR-2's three required states map to Stripe Identity's session statuses:
  `requires_input` / `processing` → **pending**; `verified` → **approved**; a session that reaches
  `canceled`, or `requires_input` past the allowed resubmission attempts → **rejected**.
- A `verified` Stripe Identity session means identity is confirmed — it does **not** mean the
  brokerage account is open and tradable. FR-39 (brokerage-side account approval as a distinct
  lifecycle) stays in force unchanged; this ADR does not collapse the two gates into one.

## Consequences

- One fewer vendor relationship than running Stripe Identity alongside a separate Persona/Sumsub
  integration — one webhook-signing secret, one compliance/PCI vendor review, one support channel,
  shared with the already-decided Stripe Billing integration (ADR 10).
- The KYC status mapping above must be implemented precisely; a session sitting in `processing`
  must not be misreported as `rejected` by a naive "not yet verified = rejected" simplification.

## Alternatives considered

- **Persona or Sumsub.** Both are viable, brief-sanctioned options with no functional objection.
  Rejected only in favor of consolidating vendor surface with Stripe Billing (ADR 10) — a
  reasonable, non-arbitrary tie-breaker given the brief left this an open "your call" choice, not a
  quality difference between providers.
