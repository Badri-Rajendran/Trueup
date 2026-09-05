# Architecture Decision Records

One file per material architectural choice, numbered sequentially, never renumbered or deleted —
a superseded decision gets a new ADR that says so, following [1](1-bitemporal-append-only-ledger.md)'s
own pattern of superseding rather than editing. Each ADR states status, context, decision,
consequences, and the alternatives it rejected.

| # | Decision | Status |
| --- | --- | --- |
| [1](1-bitemporal-append-only-ledger.md) | Bitemporal, append-only ledger | Accepted |
| [2](2-event-driven-settlement-and-available-cash.md) | Settlement is event-driven; available cash is a computed policy | Accepted |
| [3](3-time-weighted-returns.md) | Time-weighted return methodology | Accepted |
| [4](4-fifo-default-specific-id-override.md) | FIFO default with specific-lot override | Accepted |
| [5](5-withdrawable-vs-investable-cash.md) | Withdrawable vs. investable cash, free-riding guard | Accepted |
| [6](6-as-published-snapshot-cross-check.md) | As-published snapshot at period close, cross-checked | Accepted |
| [7](7-order-event-stream-and-projection.md) | Order event stream + projection; dedupe; backstop ownership | Accepted |
| [8](8-monthly-rebalance-drift-band.md) | Monthly rebalance, drift-band gated | Accepted |
| [9](9-stripe-identity-for-kyc.md) | Stripe Identity as the decided KYC provider | Accepted |
| [10](10-performance-fee-twr-high-water-mark.md) | Performance fee: TWR + high-water-mark, Stripe Billing, locked to as-published | Accepted |
| [11](11-wash-sale-handling.md) | Wash sale detection and basis adjustment | Accepted |
| [12](12-market-calendar-and-timezone-anchoring.md) | Market calendar source and timezone anchoring | Accepted |
| [13](13-azure-scheduled-jobs-not-celery.md) | Scheduled/async work: Azure Container Apps Jobs + Postgres outbox, not Celery/Redis | Accepted |
| [14](14-layered-architecture-repository-unit-of-work.md) | Layering: services/integrations/core added to MVC; repository + unit of work | Accepted |
| [15](15-session-auth-mfa-tenant-isolation.md) | Server-side session auth, mandatory adviser MFA, defence-in-depth tenant isolation | Accepted |
| [16](16-typed-money-units-price-value-objects.md) | Money/Units/Price value objects make dimension-mixing a type error | Accepted |
| [17](17-ledger-balance-trigger-and-rls-adviser-policy.md) | Database-enforced ledger balance trigger; role-aware RLS for adviser/admin reads | Accepted |
| [18](18-openai-agent-sdk-vendor.md) | OpenAI Agent SDK as the LLM vendor for the natural-language query assistant | Accepted |
| [19](19-read-only-sql-tool-safety-perimeter.md) | Read-only SQL tool safety perimeter: curated views, least-privilege role, query validator | Accepted |
| [20](20-observability-and-realtime-push.md) | Azure Application Insights for observability; SSE + Redis Pub/Sub for real-time push | Accepted |
| [21](21-alpaca-paper-trading-not-broker-api.md) | Alpaca Paper Trading API, not Broker API; simulated account-approval lifecycle | Accepted |

Still open, deferred to the S8 sub-project (see [`docs/architecture.md`](../architecture.md)):
customer surface (mobile vs. web) and adviser console vs. plain admin.
