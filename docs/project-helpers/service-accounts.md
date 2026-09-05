# External service accounts

Every third-party account the backend needs before it can run against sandbox or live integrations,
derived from `docs/decisions/*` and `docs/specs/*` — not from `provider-menu.md`'s general
suggestions, which this document supersedes for Trueup's actual choices (ADR 9, 10, 12, 18, 21).

**Rule, restated from root `CLAUDE.md`**: never commit `.env` or any real credential; never feed real
PII into a sandbox system, yours or anyone else's — use each provider's own prefab test identities.
Every credential below is stored in Azure Key Vault in deployed environments and in a local,
git-ignored `.env` for development (`.env.example` lists the variable names, never real values).

## 1. Alpaca — broker, market data, trading calendar (ADR 12, ADR 21)

- **Product: Paper Trading API** (not Broker API — ADR 21 records why: instant self-serve keys, no
  per-customer accounts, no onboarding-approval wait).
- Sign up at Alpaca, generate a paper-trading API key pair from the dashboard.
- Credentials: `ALPACA_API_KEY_ID`, `ALPACA_API_SECRET_KEY`, `ALPACA_BASE_URL` (paper endpoint).
- Also register a webhook/notification endpoint (once the app is deployed and reachable) for order
  fill events — S3 §6 ingests these through the shared `inbound_event` intake path.
- Breaks without it: FR-8 (order lifecycle), FR-9 (fills), FR-14 (daily valuation), ADR 12 (market
  calendar) — this is the single highest-priority account to create first, per `requirements.md`'s
  own build order (S1 first, but S2/S3 wired day one).
- Cost: **Free.**

## 2. Plaid — bank linking, ACH, bounce/re-auth webhooks (S2 §5)

- Sign up for Plaid, use the **Sandbox** environment (not Development/Production).
- Enable **Transfer** in the Sandbox dashboard for simulated ACH deposits/withdrawals and bounce
  events. If Transfer isn't granted, deposits/bounces (S2 §5.2) fall back to simulated ACH events
  posted through the same `inbound_event` intake path — the ledger mechanism (ADR 2) is identical
  either way, so this is a fallback, not a blocker.
- Credentials: `PLAID_CLIENT_ID`, `PLAID_SECRET` (Sandbox secret), `PLAID_ENV=sandbox`,
  `PLAID_WEBHOOK_URL`.
- Use Plaid's published Sandbox test users/institutions (e.g. `user_good`) — never a real bank login.
- Breaks without it: FR-4 (bank linking), FR-5 (deposits/withdrawals), FR-6 (bounce handling), FR-43
  (re-auth).
- Cost: **Free.**

## 3. Stripe — KYC identity and fee billing (ADR 9, ADR 10)

One account, two products, both in **test mode**:

- **Stripe Identity**: create verification sessions; use Stripe's published test document/selfie
  flow, never a real ID.
- **Stripe Billing + Elements**: create products/prices for the performance fee, use Stripe's
  published test cards for payment-method attachment (S10 §7).
- Credentials: `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SECRET_KEY` (test mode), plus a **separate webhook
  signing secret per endpoint** — `STRIPE_WEBHOOK_SECRET_IDENTITY`, `STRIPE_WEBHOOK_SECRET_BILLING`
  (Stripe issues one per registered webhook endpoint in the dashboard, not one per account).
- Breaks without it: FR-1–3, FR-39 (KYC), FR-45–48 (fee accrual/charge/dunning).
- Cost: **Test mode free.** Live mode is the one cost the user has explicitly accepted.

## 4. OpenAI — natural-language query assistant (ADR 18)

- Create an API key from the OpenAI platform dashboard; the user has confirmed prepaid credits cover
  this, so no free-tier workaround is needed.
- Credentials: `OPENAI_API_KEY`, `OPENAI_ORG_ID` (optional, if the account has multiple orgs).
- Set a **usage/spend limit** in the OpenAI dashboard as a backstop underneath NFR-16's own
  application-layer caps (per-customer daily query cap, per-conversation tool-call limit) — belt and
  suspenders, not a replacement for either.
- Breaks without it: FR-49–54 (the entire S11 chat assistant); nothing else in the platform depends
  on it — `LlmAgentPort` (ADR 18) keeps this failure domain isolated.
- Cost: **User's prepaid credits**; no free tier exists.

## 5. Microsoft Azure — hosting, data, jobs, observability (ADR 13, ADR 15, ADR 20)

The user has a $200 Azure credit; resources below are sized to stay well inside it for the six-week
build (NFR-11), not for a permanent production footprint.

| Resource | Purpose | Suggested SKU | Approx. cost |
| --- | --- | --- | --- |
| Azure Database for PostgreSQL — Flexible Server | The ledger's database of record | Burstable B1ms | ~$12–15/mo |
| Azure Cache for Redis | Sessions, rate-limit counters, SSE Pub/Sub fanout (ADR 13/20) — never financial state | Basic C0 | ~$16/mo |
| Azure Container Registry | CI/CD image storage | Basic | ~$5/mo |
| Azure Container Apps + Jobs | API, the always-on outbox-draining worker, and scheduled batch jobs (ADR 13) | Consumption plan | Pay-per-use, small at this scale |
| Azure Key Vault | Secrets — provider API keys, DB credentials, the `app_bypass` RLS-bypass credential (ADR 17) kept separate from the web API's own — **plus an RSA key** (`AZURE_KEYVAULT_WRAP_KEY_NAME`) that wraps per-record data keys for encrypted columns (ADR 23) | Standard | ~$0.03/10k operations, negligible |
| Azure Application Insights + Azure Monitor | Observability, alert rules (ADR 20, S12 §4) | Pay-as-you-go, 5 GB/mo free ingestion | Likely $0 at this scale |

Rough total: **~$35–40/month** of infrastructure spend, comfortably inside the $200 credit across a
six-week build with room for iteration. Re-check current Azure pricing before committing — prices
drift and region affects cost.

- Credentials needed: a **service principal** (App Registration) for GitHub Actions CI/CD —
  `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `AZURE_CLIENT_SECRET` (or federated
  OIDC credentials, preferred over a long-lived secret where the CI setup supports it) — plus each
  resource's own connection string/key, which lives in Key Vault, never in `.env` or the repo.
- Breaks without it: the entire deployed environment (ADR 13's jobs, ADR 15's sessions/tenant
  isolation, ADR 20's observability and real-time push) — local Docker Compose development does not
  require Azure at all.
- Cost: **User's $200 credit.**

## 6. GitHub — CI/CD (already in use)

- No new account — the repository already exists under the user's GitHub account.
- Add the Azure service-principal credentials above as **GitHub Environment secrets** (root
  `CLAUDE.md`: "Store secrets in GitHub Environments / Azure Key Vault — never in the repo or
  workflow files"), not repository-level secrets, so production deploys require the environment's
  approval gate.
- Cost: **Free** (public or standard private-repo Actions minutes at this project's scale).

## 7. Optional — market-data fallback (S0 §3, "if used")

The foundation spec names Polygon.io or Twelve Data as an optional fallback if Alpaca's own market
data proves insufficient for any reason. Not required to start; add only if a real gap appears.

- Credentials (if adopted): `POLYGON_API_KEY` or `TWELVEDATA_API_KEY`.
- Cost: **Free tier** on either provider.

## Not required

- **The custodian file** (FR-30–33) — Trueup's own labelled simulator, no external account.
- **Email/SMS** — no provider is committed; S3 §9 leaves proactive customer notification (push vs.
  email) as an explicit open parameter, not yet a build dependency.

## Priority order to register

Matches `requirements.md`'s own build order and the T+24h checkpoint (a deposit must already be
buying real paper positions):

1. Alpaca (paper trading keys — instant)
2. Plaid (sandbox — instant)
3. Stripe (test mode — instant)
4. Azure (subscription + service principal — needed once deployment, not just local dev, starts)
5. OpenAI (only needed once S11 implementation begins, not for S1–S10)
