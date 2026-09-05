# Trueup — Requirements

Derived line-by-line from [project-description.md](project-description.md) (the brief). Every
requirement below cites the line(s) it comes from. IDs are the traceability keys used in ADRs
(`docs/decisions/`), the architecture doc, sub-project specs, and test names — do not renumber them.

FR-37 onward and NFR-13/14 are not brief-derived — they came out of a 2026-09-04 gap review (missed
corner cases the brief doesn't spell out) and an explicit user decision to add Stripe-based KYC and
performance-fee billing. Each cites its source (a gap finding or a recorded decision) instead of a
brief line number, since none exists.

## Functional Requirements

### Identity & onboarding (brief lines 14, 18, 25, 34)
| ID | Requirement |
| --- | --- |
| FR-1 | Run a real third-party KYC check per customer before funding is permitted. |
| FR-2 | Surface all three KYC states — pending, approved, rejected — not just approved. |
| FR-3 | Hard-gate: no funding and no investing until KYC passes. |
| FR-39 | Track brokerage-side account approval (e.g. the custodian's own OFAC/sanctions/account-opening review) as a lifecycle distinct from the identity provider's KYC verdict; funding and investing require both to be approved, not just KYC. |

### Funding (lines 14, 16, 18, 25, 35, 59)
| ID | Requirement |
| --- | --- |
| FR-4 | Link an external bank account via open banking (Plaid or equivalent); card funding is prohibited. |
| FR-5 | Support deposits and withdrawals. |
| FR-6 | Handle a deposit that bounces after the cash was already invested; define what the customer sees. |
| FR-41 | Withdrawals settle only to the bank account verified during funding (FR-4); no withdrawal to an unverified destination (AML control). |
| FR-42 | A customer may have at most one active linked bank account for v1; linking a new one supersedes the prior link for future withdrawals, and does not affect obligations already pending against the prior account. |
| FR-43 | Handle Plaid re-authentication being required (e.g. `ITEM_LOGIN_REQUIRED`) by pausing the dependent deposit/withdrawal flow and prompting re-linking; never silently fail or retry against a stale bank Item. |

### Portfolios & orders (lines 7, 18, 33, 55)
| ID | Requirement |
| --- | --- |
| FR-7 | Exactly four model portfolios, composed of US-listed equities and bonds only. |
| FR-8 | Place real (paper) orders with full lifecycle: submitted → partially filled → filled. |
| FR-9 | Receive fills by webhook, not polling only; process idempotently — a replayed fill must not double positions. |
| FR-10 | Trades above a configurable threshold require explicit user approval before execution. |
| FR-38 | Release the FR-10 cash hold immediately when an order reaches a terminal non-filled state (`rejected`, `canceled`, or `expired`); a stranded hold that never releases understates available cash indefinitely. |

### Ledger & positions (lines 42, 43, 44)
| ID | Requirement |
| --- | --- |
| FR-11 | Positions are units to six decimal places; value = units × price; cash is itself a position. Units, price, and money are separate dimensions and must never be conflated. |
| FR-12 | Every ledger movement is immutable double-entry: both legs post across cash and assets, plus fees. |
| FR-13 | Model the T+1 settlement gap explicitly — settled and available cash diverge and reconverge; unsettled proceeds cannot be withdrawn. |

### Valuation & returns (lines 3, 10, 36, 48)
| ID | Requirement |
| --- | --- |
| FR-14 | Value the whole book daily against closing prices. |
| FR-15 | Handle a missing daily close and a stale price honestly — surface the condition, never silently substitute. |
| FR-16 | Report a period return figure using one declared, defended methodology (time-weighted or money-weighted). |
| FR-17 | Cash flows (deposits/withdrawals) must never pollute the reported return — a deposit is not a return. |
| FR-18 | Customers can view account balance, period return, and full transaction history. |
| FR-40 | Distinguish an expected non-trading day (US market holiday, per exchange calendar) from an unexpected missing/stale close (FR-15) — only the latter is a reconciliation break; a holiday must never be surfaced as one. |

### Tax lots (lines 18, 45)
| ID | Requirement |
| --- | --- |
| FR-19 | Every buy opens a new tax lot. |
| FR-20 | Sells consume lots under one declared, defended policy (FIFO or specific-identification). |
| FR-21 | Realized and unrealized gains/losses derive from tax lot state, never a parallel tally. |
| FR-22 | Produce a tax-time transaction export derived from lot data. |
| FR-37 | Detect and handle wash sales arising from automated rebalancing (a loss sale followed by a repurchase of the same or a substantially identical security within 30 days): disallow the realized loss and carry the disallowed amount into the replacement lot's basis, per IRS wash-sale rules. |

### Corporate actions & dividends (lines 12, 18, 37, 46, 47, 56, 57)
| ID | Requirement |
| --- | --- |
| FR-23 | Handle the dividend lifecycle: declared → ex-date → pay-date, with cash arriving days after entitlement. |
| FR-24 | Handle stock splits (e.g. 2-for-1): doubles units, halves per-unit cost basis, changes neither market value nor return. |

### Returns integrity under restatement (lines 3, 12, 18, 49, 56)
| ID | Requirement |
| --- | --- |
| FR-25 | A late-arriving correction (dividend, split, or corrected closing price) affecting an already-reported period restates that period's return to the correct value. |
| FR-26 | Both the originally-published and the corrected figures remain independently queryable forever; history is never overwritten in place. |

### Rebalancing (lines 7, 18, 50)
| ID | Requirement |
| --- | --- |
| FR-27 | Rebalance each portfolio monthly against model target weights. |
| FR-28 | Order generation respects drift from target, order minimums, fractional-share rules, and a cash buffer. |
| FR-29 | Correctly represent a book left mid-flight overnight due to partial fills during rebalancing. |

### Reconciliation (lines 16, 18, 37, 51, 60)
| ID | Requirement |
| --- | --- |
| FR-30 | Every morning, reconcile positions, cash, and transactions against an external custodian file. |
| FR-31 | Reconciliation breaks are surfaced on a screen with an aging indicator, not buried in a log line. |
| FR-32 | Detect a single tampered/incorrect position in the custodian file. |
| FR-33 | The custodian file is a clearly labelled simulator able to inject a late dividend and a corrected closing price. |
| FR-44 | Resolving a detected reconciliation break is a manual, human action; the system never auto-corrects the ledger or the custodian file to eliminate a break. |

### Client surfaces & statements (lines 10, 18, 25, 27)
| ID | Requirement |
| --- | --- |
| FR-34 | A customer-facing surface (mobile app and/or web — implementer's scoping call, must be defended) for viewing the portfolio, balance, return, transaction history, and approving trades above threshold. |
| FR-35 | An adviser console (or admin equivalent — implementer's scoping call, must be defended). |
| FR-36 | Exportable statements / transaction history at tax time. |

### Performance fees (core v1 — promoted 2026-09-04 from the brief's stretch ladder; user decision)
| ID | Requirement |
| --- | --- |
| FR-45 | Compute a daily performance-fee accrual from TWR-derived gain (ADR 3) against a per-customer high-water-mark; never accrue a fee on a gain that merely recovers a prior loss. |
| FR-46 | Charge the accrued fee monthly via the customer's Stripe-linked payment method (ADR 10); never debit Alpaca investable cash or force a sell-to-cover to pay a fee. |
| FR-47 | Lock the fee basis to the as-published figure (ADR 6) at charge time; a later restatement of that period does not reopen or adjust an already-charged fee — disclosed as a documented limitation, not resolved by a refund/reclaim mechanism. |
| FR-48 | Handle a failed monthly fee charge with a defined retry/dunning state visible to the customer; a failed charge is never silently dropped. |

### Natural-language query assistant (new scope — added 2026-09-04; user decision, not brief-derived)
| ID | Requirement |
| --- | --- |
| FR-49 | Chat interface: an authenticated customer asks natural-language questions about their own balance, positions, transactions, tax lots, dividends, and returns; answers are derived from live database queries, not fabricated. |
| FR-50 | The assistant's data access is limited to a curated set of read-model views; it must never query raw ledger tables (`posting`, `journal_entry`, `order_event`, etc.) or any relation outside an explicit allow-list. |
| FR-51 | Every assistant-issued query executes under the same session-scoped identity (customer_id, role) as the rest of the application (ADR 15/17) — a query must never return another customer's data regardless of phrasing. |
| FR-52 | Support both a live/current-state answer and an as-published historical answer (ADR 6); any answer tied to a specific period must state explicitly whether it is live or as-published. |
| FR-53 | Every tool invocation (schema request, SQL query) and its result metadata, plus token/cost usage, is recorded in an audit trail; usage is capped per customer per day, and a bounded per-conversation tool-call limit prevents runaway cost. |
| FR-54 | The assistant declines to answer, rather than fabricate, when a question needs data outside its curated views or when a query returns no matching rows. |

## Non-Functional Requirements

| ID | Requirement | Source |
| --- | --- | --- |
| NFR-1 | Immutability — the platform is regulated; ledger entries are append-only and history is never rewritten. | line 12 |
| NFR-2 | Double-entry integrity — the book always balances; both legs post, or nothing posts. | line 43 |
| NFR-3 | Dimensional safety — units, price, and money are never conflated in storage or computation. | line 42 |
| NFR-4 | Auditability — as-published and as-corrected figures both remain permanently queryable. | line 49 |
| NFR-5 | Idempotency — webhook-driven event ingestion is safe under replay. | line 58 |
| NFR-6 | Honest degradation — missing or stale market data is surfaced, never masked. | line 36 |
| NFR-7 | Return integrity — correct under both cash flows and retroactive corrections; explicitly the hardest-graded property. | lines 48, 77 |
| NFR-8 | Single currency — USD only, a deliberate simplification. | line 27 |
| NFR-9 | US market scope — US-listed securities, US market hours, T+1 settlement, US tax-lot rules. | line 27 |
| NFR-10 | Buy-not-build — custody, identity verification, and bank linking come from external providers. | lines 14, 27 |
| NFR-11 | Delivery timeline — live in six weeks; an internal T+24h checkpoint expects a deposit already buying real paper positions. | lines 18, 64 |
| NFR-12 | Integration liveness — brokerage/custody, KYC, and open banking must be live; market data live or simulated; the custodian file may be simulated if clearly labelled. Order placement, fills, positions, and market data are live against Alpaca; the brokerage-side account-approval verdict itself is simulated, since Alpaca Paper Trading API (ADR 21) has no per-customer onboarding verdict to be live against. | lines 33–38; qualified by ADR 21 |
| NFR-13 | Temporal anchoring — every `effective_date` and daily-boundary computation (valuation, settlement, reconciliation) is anchored to America/New_York (the US market timezone), never server-local time or a UTC-naive boundary. | gap finding #14 |
| NFR-14 | Client-side idempotency — state-changing customer-initiated requests (deposit, withdrawal, order placement) accept a client-generated idempotency key; a repeated key with the same payload returns the original result rather than creating a duplicate. | gap finding #15 |
| NFR-15 | AI security — model input (chat messages) and model output (generated SQL, answers, and any data reflected back through a tool, including free-text fields) are untrusted; the enforcement boundary is the DB role + RLS + query validator, never the system prompt alone. | root `CLAUDE.md`, OWASP LLM Top 10 |
| NFR-16 | Cost/rate governance — a per-customer daily query cap, a per-conversation tool-call iteration cap, and a per-query statement timeout and row limit, enforced independent of model behavior. | root `CLAUDE.md`'s rate/cost-limit rule |
| NFR-17 | Observability — every documented "should alert" failure condition (a missing job run, a dead-lettered outbox row, a snapshot cross-check failure, and others) maps to a concrete, routed Azure Monitor alert rule, not prose alone. | production/real-time efficiency review, 2026-09-04 |
| NFR-18 | Real-time visibility — an order fill, a KYC verdict, and a new reconciliation break push to an open customer/adviser session within seconds via SSE, rather than being visible only on the next poll. | production/real-time efficiency review, 2026-09-04 |

## Acceptance Scenarios ("Live fire", brief lines 53–60)

| # | Scenario | Exercises |
| --- | --- | --- |
| 1 | Onboard with sandbox identity, link a Plaid test bank, deposit, invest into a model — orders land at the broker. | FR-1–9 |
| 2 | Deliver a corrected close for three days ago; corrected figure shown, published history preserved. | FR-25, FR-26 |
| 3 | Run a 2-for-1 split: units double, basis halves, return unchanged. | FR-24 |
| 4 | Replay a fill webhook: positions must not double. | FR-9, NFR-5 |
| 5 | Bounce a deposit after the cash was invested: defined customer-facing outcome. | FR-6 |
| 6 | Tamper one position in the custodian file: reconciliation screen finds it. | FR-32 |

## Explicitly Out of Core Scope (stretch ladder, brief lines 66–73)

Not required for v1: USDC deposits / idle-cash sweep (testnet); recurring deposits with standing
instructions; model portfolio versioning; an accountant-acceptable tax PDF; adviser bulk rebalance
approval (maker-checker at portfolio scale).

Also out of v1 scope (gap review, 2026-09-04): re-screening or revoking KYC/account approval after a
customer is already approved (e.g. later added to a sanctions watchlist) — gap finding #6; deposit/
withdrawal amount limits (NACHA/ACH caps) — gap finding #10, deferred to S2's own spec; custodian file
format/schema and match granularity — gap finding #13, deferred to S7's own spec; corporate actions
other than dividends and splits (mergers, spin-offs, delistings, ticker changes) — gap finding #5;
ledger backup/PITR policy and fractional-share-ineligible securities handling — gap finding #17,
treated as inherited from root `CLAUDE.md`'s generic security/infra stance unless a sub-project spec
says otherwise. (Multi-tenant row-level isolation, also originally part of gap finding #17, is no
longer deferred — see ADR 15.)

Note: daily-accrued/monthly-charged performance fees were on this stretch ladder in the original
brief but were promoted to core v1 scope on 2026-09-04 by explicit user decision — see the
Performance fees section above (FR-45–48) and ADR 10. This is a deliberate deviation from the
brief's own stated v1 boundary, made with the cost against NFR-11's six-week timeline acknowledged.

## Sub-Project Decomposition

The brief spans more ground than a single design can hold. It decomposes into eleven sub-projects,
each getting its own spec under `docs/specs/`:

| # | Sub-project | Requirements | Depends on |
| --- | --- | --- | --- |
| S1 | Ledger & units core | FR-11–13, NFR-1–3 | — |
| S2 | Identity & funding rails | FR-1–6 | S1 |
| S3 | Orders & custody | FR-7–10, FR-29 | S1 |
| S4 | Valuation & returns | FR-14–18 | S1 |
| S5 | Tax lots & corporate actions | FR-19–24 | S1, S4 |
| S6 | Restatement engine | FR-25–26 | S4, S5 |
| S7 | Reconciliation & custodian simulator | FR-30–33 | S1 |
| S8 | Surfaces (customer, adviser, statements) | FR-34–36 | progressive |
| S9 | Rebalancing (also owns model portfolio target-weight data — gap finding #16) | FR-27–28 | S3, S4 |
| S10 | Performance fees | FR-45–48 | S1, S4, S6 |
| S11 | Natural-language query assistant | FR-49–54, NFR-15–16 | S1, S4, S5, S6 |
| S12 | Production operations & performance | NFR-17–18 | S0–S11 (operational layer beneath all of them) |

Build order (brief line 64): **S1 first** — get the two-dimension (units vs. money) problem right
before any UI. S2/S3 integrations wired day one, since the T+24h checkpoint expects a deposit
buying real paper positions. S4 second. S5 precedes S6; S6 is the differentiator and gets real
hours budgeted. S7 and S9 follow. S10 follows S6 (its fee-lock depends on the restatement watermark
existing). S11 also follows S6 (its as-published views depend on the same watermark) and reads S5's
lot/gain data. S8 grows alongside the rest.

## Decisions Requiring an ADR

Several requirements above explicitly delegate a choice ("pick and defend") or surfaced one during
design. Each is recorded as an ADR in [`docs/decisions/`](../decisions/):

| Decision | Requirement(s) | ADR |
| --- | --- | --- |
| Bitemporal append-only ledger | FR-12, FR-25, FR-26, NFR-1, NFR-4 | [1](../decisions/1-bitemporal-append-only-ledger.md) |
| Event-driven settlement; available cash as policy | FR-13 | [2](../decisions/2-event-driven-settlement-and-available-cash.md) |
| Time-weighted return methodology | FR-16, FR-17 | [3](../decisions/3-time-weighted-returns.md) |
| FIFO default, specific-ID override | FR-20 | [4](../decisions/4-fifo-default-specific-id-override.md) |
| Withdrawable vs. investable cash, free-riding guard | FR-13 | [5](../decisions/5-withdrawable-vs-investable-cash.md) |
| As-published snapshot with derivation cross-check | FR-25, FR-26, NFR-4 | [6](../decisions/6-as-published-snapshot-cross-check.md) |
| Order event stream + projection; dedupe key; backstop ownership | FR-8, FR-9, FR-29, NFR-5 | [7](../decisions/7-order-event-stream-and-projection.md) |
| Monthly rebalance, drift-band gated | FR-27, FR-28 | [8](../decisions/8-monthly-rebalance-drift-band.md) |
| Stripe Identity as the decided KYC provider | FR-1–3, FR-39 | [9](../decisions/9-stripe-identity-for-kyc.md) |
| Performance fee: TWR + high-water-mark, charged via Stripe Billing, locked to as-published | FR-45–48 | [10](../decisions/10-performance-fee-twr-high-water-mark.md) |
| Wash sale detection and basis adjustment | FR-37, FR-21 | [11](../decisions/11-wash-sale-handling.md) |
| Market calendar source and timezone anchoring | FR-40, NFR-13 | [12](../decisions/12-market-calendar-and-timezone-anchoring.md) |
| Scheduled/async work: Azure Container Apps Jobs + Postgres outbox, not Celery/Redis | cross-cutting (S4, S7, S9, S10) | [13](../decisions/13-azure-scheduled-jobs-not-celery.md) |
| Backend layering: services/integrations/core added to MVC; repository + unit of work | cross-cutting (all sub-projects) | [14](../decisions/14-layered-architecture-repository-unit-of-work.md) |
| Server-side session auth, mandatory adviser MFA, defence-in-depth tenant isolation | FR-34, FR-35, gap finding #17 | [15](../decisions/15-session-auth-mfa-tenant-isolation.md) |
| Money/Units/Price value objects make dimension-mixing a type error | NFR-3 | [16](../decisions/16-typed-money-units-price-value-objects.md) |
| Database-enforced ledger balance trigger; role-aware RLS for adviser/admin reads | NFR-1, NFR-2, FR-31 | [17](../decisions/17-ledger-balance-trigger-and-rls-adviser-policy.md) |
| OpenAI Agent SDK as the LLM vendor for the natural-language query assistant | FR-49, NFR-15 | [18](../decisions/18-openai-agent-sdk-vendor.md) |
| Read-only SQL tool safety perimeter: curated views, least-privilege DB role, query validator | FR-50, FR-51, NFR-15, NFR-16 | [19](../decisions/19-read-only-sql-tool-safety-perimeter.md) |
| Azure Application Insights for observability; SSE + Redis Pub/Sub for real-time push | NFR-17, NFR-18 | [20](../decisions/20-observability-and-realtime-push.md) |
| Alpaca Paper Trading API, not Broker API; simulated FR-39 account-approval lifecycle | FR-39, NFR-12 | [21](../decisions/21-alpaca-paper-trading-not-broker-api.md) |
| Alpaca fills arrive over a `trade_updates` websocket, not an HTTP webhook | FR-8, FR-9, NFR-5 | [22](../decisions/22-alpaca-trade-updates-websocket-intake.md) |
| Azure Key Vault envelope encryption for field-level secrets at rest | FR-4, FR-34, NFR-9 | [23](../decisions/23-key-vault-envelope-encryption.md) |

Still open, deferred to their owning sub-project (do not block S1):
- Customer surface — mobile app vs. web (line 27) → S8.
- Adviser console vs. plain admin (line 27) → S8.

Multi-tenant row-level isolation, previously deferred under gap finding #17, is now decided by
[ADR 15](../decisions/15-session-auth-mfa-tenant-isolation.md) (application-layer scoping plus
Postgres Row-Level Security). Ledger backup/PITR policy and fractional-share-ineligible securities
handling remain deferred as gap finding #17 originally stated.

## What Is Graded Hardest (line 77)

Return-figure integrity under flows and corrections (FR-16, FR-17, FR-25, FR-26, NFR-7), tax lots
(FR-19–22), and whether reconciliation actually catches a planted break (FR-32).
