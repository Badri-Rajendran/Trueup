# 18 — OpenAI Agent SDK as the LLM vendor for the natural-language query assistant

## Status

Accepted

## Context

The user decided (2026-09-04) to add a natural-language query assistant (S11, FR-49–54): a chat
interface where a customer asks free-form questions about their own account data, answered by an
agent with two tools — reading the database schema and executing a read-only `SELECT`. This has no
precedent in the brief; it is new scope, and it introduces a vendor relationship none of S1–S10 have:
every existing external integration (Alpaca, Plaid, Stripe) is the customer's *own* regulated
financial-services provider, chosen because the brief or the user required it. OpenAI is not a
financial-services provider the customer has a relationship with — it is a third party the platform
sends a customer's own real financial figures to, on the customer's behalf, in order to answer their
question. That distinction is the reason this gets its own ADR rather than being treated as "just
another integration."

## Decision

**OpenAI's Agent SDK** (Python), using native function-tool calling for `get_database_schema` and
`execute_read_only_sql`, is the LLM vendor and orchestration layer for S11.

- **Model choice is a tunable setting, not an architectural decision.** Start with a cost-efficient
  ("mini"-tier) model behind `app/config.py` settings (per the foundation spec's configuration
  rules) — NFR-11's six-week budget favors starting cheap and upgrading only if answer quality
  demands it, and nothing in this design depends on which specific model is configured.
- **Data-handling flag, stated explicitly rather than assumed away.** The OpenAI API path (not
  consumer ChatGPT) does not train on submitted data by default, but this design assumes the
  strictest data-retention setting available on the account (zero or shortest-available retention)
  is confirmed/enabled before this reaches real customer data — a real financial figure, even though
  scoped to one customer by the tool's own guardrails (ADR 19), is now leaving the system to a third
  party for the first time. This is recorded as a dependency of going live with real customers, not
  a compliance question this ADR can resolve on its own.
- **Streaming** is used end-to-end (Agent SDK's native streaming) to drive the SSE API contract
  (`docs/specs/11-nl-query-assistant.md`), rather than buffering a complete response before returning
  anything to the customer.
- **This integration follows ADR 14's ports-and-adapters pattern** like every other external
  provider: `LlmAgentPort` in `app/integrations/openai/`, with a fake adapter for contract tests —
  OpenAI is architecturally just another provider behind a port, even though its data-handling
  implications above are novel for this platform.

## Consequences

- S11 is the first sub-project whose "external integration" section carries a data-privacy
  consequence distinct from "must be live" (NFR-12) — it must be live *and* have its data-retention
  posture confirmed, which is a business/compliance step outside this ADR's scope to complete.
- Model cost is a new, ongoing operating expense with no natural cap from the rest of the system —
  ADR 19's usage limiter (FR-53, NFR-16) is not optional hardening, it is the only thing standing
  between this feature and an open-ended cost.
- Adding a second LLM vendor later (a fallback provider, or a self-hosted model) is a new adapter
  behind the same `LlmAgentPort`, not a redesign — the port boundary is deliberately vendor-neutral.

## Alternatives considered

- **A self-hosted / open-weight model.** Avoids sending any customer data to a third party at all,
  which would remove the data-handling flag above entirely. Rejected for v1: this repo has no
  existing ML-serving infrastructure to build on, and standing one up (GPU provisioning, model
  hosting, inference serving) is a materially larger build than NFR-11's six-week timeline can
  absorb alongside S1–S10. Revisitable post-v1 if the data-handling flag above proves genuinely
  blocking rather than merely a configuration step.
- **A different hosted LLM vendor** (e.g. another major provider's API). No functional objection —
  this was the user's explicit choice from the brief's own pattern of naming a vendor and moving on
  (as with Stripe, ADR 9/10), not a quality comparison this ADR needed to adjudicate.
