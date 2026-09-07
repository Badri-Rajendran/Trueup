# Architecture Decision Records

One file per material architectural choice, numbered sequentially, never renumbered or deleted —
a superseded decision gets a new ADR that says so, following [1](01-bitemporal-append-only-ledger.md)'s
own pattern of superseding rather than editing. Each ADR states status, context, decision,
consequences, and the alternatives it rejected.

| # | Decision | Status |
| --- | --- | --- |
| [1](01-bitemporal-append-only-ledger.md) | Bitemporal, append-only ledger | Accepted |
| [2](02-event-driven-settlement-and-available-cash.md) | Settlement is event-driven; available cash is a computed policy | Accepted |
| [3](03-time-weighted-returns.md) | Time-weighted return methodology | Accepted |
| [4](04-fifo-default-specific-id-override.md) | FIFO default with specific-lot override | Accepted |
| [5](05-withdrawable-vs-investable-cash.md) | Withdrawable vs. investable cash, free-riding guard | Accepted |
| [6](06-as-published-snapshot-cross-check.md) | As-published snapshot at period close, cross-checked | Accepted |
| [7](07-order-event-stream-and-projection.md) | Order event stream + projection; dedupe; backstop ownership | Accepted |
| [8](08-monthly-rebalance-drift-band.md) | Monthly rebalance, drift-band gated | Accepted |
| [9](09-stripe-identity-for-kyc.md) | Stripe Identity as the decided KYC provider | Accepted |
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
| [22](22-alpaca-trade-updates-websocket-intake.md) | Alpaca fills arrive over a `trade_updates` websocket, not an HTTP webhook | Accepted |
| [23](23-key-vault-envelope-encryption.md) | Azure Key Vault envelope encryption for field-level secrets at rest | Accepted |
| [24](24-mcp-agent-surface-approval-queue.md) | MCP agent surface: read-only tools plus a durable, adviser-approved write queue | Accepted |
| [25](25-order-cancellation.md) | Order cancellation is a broker request, never a local state mutation | Accepted |
| [26](26-portfolio-performance-series.md) | Portfolio performance series sourced from `sub_period_return`, live vs. as-published, allowlisted range | Accepted |
| [27](27-profile-personal-data.md) | Customer profile personal data: storage, access, and validation | Accepted |

Still open, deferred to the S8 sub-project (see [`docs/architecture.md`](../architecture.md)):
customer surface (mobile vs. web) and adviser console vs. plain admin.
