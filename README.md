# Trueup

A regulated retail-investing platform — USD, US-listed equities and bonds. Customers pass identity
checks, deposit from a linked bank account, buy into one of four model portfolios, and are
rebalanced monthly. Positions are units valued daily; every movement is an immutable double-entry
entry across cash and assets; trades settle T+1; every buy opens a tax lot. History is never
rewritten — a late dividend, a split, or a corrected price restates the affected period's return
while the as-published figure stays queryable.

Full brief: [`docs/requirements/project-description.md`](docs/requirements/project-description.md).

## Integration status

Every slot is labelled honestly, per
[`docs/requirements/real-vs-simulated-rules.md`](docs/requirements/real-vs-simulated-rules.md).

| Slot | Provider | Status |
| --- | --- | --- |
| Brokerage / custody | Alpaca Paper Trading API | **Planned live** — order placement, fills, and positions are real against Alpaca's paper infrastructure. The per-customer *account-approval verdict* is **simulated**, because this product has no such verdict to be live against ([ADR 21](docs/decisions/21-alpaca-paper-trading-not-broker-api.md)). |
| Market data | Alpaca | **Planned live** |
| Trading calendar | Alpaca | **Planned live** |
| Identity / KYC | Stripe Identity | **Planned live** (test mode) |
| Bank linking / ACH | Plaid | **Planned live** (sandbox) |
| Fee billing | Stripe Billing | **Live** (test mode) — `POST /payment-methods` genuinely calls Stripe's API; verified both via the real-adapter contract test (`requires_credentials`) and a live request against the deployed MVP |
| Custodian file | Built by us | **Simulated** — a deliberate simulator that generates the awkward cases (FR-33) |

"Planned live" means the adapter and its port exist and the contract suite runs against both the
real adapter and its fake, but the sandbox credentials are not yet issued. Each row flips to
**live** once its keys are in place and its contract tests run green against the real sandbox.
Nothing is presented as live before that.

## Deployment

An MVP is deployed to Azure Container Apps (`trueup-mvp-rg`, `centralus`):

- Frontend: `https://frontend.proudmeadow-36949862.centralus.azurecontainerapps.io`
- Backend API: `https://backend.proudmeadow-36949862.centralus.azurecontainerapps.io` (external
  ingress kept for webhook reachability; the frontend's own nginx proxies `/api` and `/health` to
  it over the environment's internal network, not the public FQDN — see
  `frontend/nginx.conf.template`)

Resources: Postgres Flexible Server (`trueup-mvp-pg`, Burstable B1ms), Azure Container Registry
(`trueupmvpacr`), a Key Vault (`trueup-mvp-kv`) backing real envelope encryption via the backend's
system-assigned managed identity (no `LOCAL_CIPHER_KEY` in this environment), and Redis running as
an internal-only Container App (ADR 13/15: sessions and rate limits only, never financial state).

**Deliberate MVP-speed shortcuts, not silent gaps — tracked here until hardened:**
- Postgres allows public access from any IP (`--public-access 0.0.0.0-255.255.255.255`) rather than
  VNet-integrated private access.
- Three domains are still mocked client-side, honestly labelled "Simulated" in the UI: tax lots,
  the admin customer directory/detail/KYC-override, and statement export — S8's `/lots`,
  `/admin/customers*`, and `/admin/kyc-overrides/<id>` routes don't exist yet
  (`docs/superpowers/specs/2026-09-05-frontend-completion-design.md` has the full design for
  closing this).
- No real-time SSE push (ADR 20/S12 §6) — every screen refetches on mount instead, the documented
  fallback.
- No new automated test coverage was added for this pass (explicit scope cut — ship fast, harden
  after); the exhaustive frontend test suite is tracked in the same design doc above.
- Alpaca and Plaid stay "Planned live" (unchanged this pass) — only Stripe Billing's
  `POST /payment-methods` was verified genuinely live this deployment, via Stripe's fixed
  test-mode payment-method tokens (`pm_card_visa` etc.), confirmed against the real Stripe test
  API both by the `requires_credentials` contract test and a live request against the deployed URL.

## Architecture

- Design specs: [`docs/specs/`](docs/specs/) — S0 (foundation) through S12 (production operations).
- Decisions: [`docs/decisions/`](docs/decisions/) — one ADR per material architectural choice.
- Requirements: [`docs/requirements/requirements.md`](docs/requirements/requirements.md) — 48 FRs,
  18 NFRs, each traceable to the brief.
- Build plan: [`docs/delivery/backend-build-plan.md`](docs/delivery/backend-build-plan.md) — how
  S0–S4 gets built, in what order, and what must be green before each step.
- Decision log: [`DECISION-LOG.md`](DECISION-LOG.md) — timestamped record of what was decided,
  assumed, and cut. Distinct from the ADRs: those say why the architecture is shaped this way,
  this says what happened and when.

| Layer | Technology |
| --- | --- |
| Backend | Python 3.12 + Flask |
| ORM | SQLAlchemy 2 (no Flask-SQLAlchemy — the session belongs to the unit of work) |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Frontend | React |
| Containers | Docker / Docker Compose |
| CI/CD | GitHub Actions |
| Cloud | Microsoft Azure |

## Getting started

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```sh
make up                 # PostgreSQL on :5433, Redis on :6380
make env                # create .env from .env.example
make install            # install backend dependencies
make migrate            # apply migrations
make dev                # run the API at http://localhost:5000
```

Then fill in `SECRET_KEY` and `LOCAL_CIPHER_KEY` in `.env`:

```sh
python3 -c "import secrets; print(secrets.token_urlsafe(48))"                      # SECRET_KEY
python3 -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"    # LOCAL_CIPHER_KEY
```

Provider credentials can stay blank — the app starts without them, and each real adapter refuses
to operate rather than silently substituting a fake. See
[`docs/project-helpers/service-accounts.md`](docs/project-helpers/service-accounts.md) for what to
register and where each key comes from.

**Ports 5433 and 6380 are deliberate**, not typos: the defaults are avoided so Trueup cannot
collide with another project's database on the same machine.

## Working on it

```sh
make check              # everything CI runs: lint, types, import rules, tests
make test               # the whole suite
make test-unit          # value objects, cash policy, TWR math — no database
make test-integration   # repositories, append-only guard, RLS policies
make test-api           # controllers via the Flask test client
make test-contract      # each port's real adapter against its fake, same suite
make migration M="..."  # autogenerate a migration
```

`make help` lists every target.

Tests run against **real PostgreSQL, never SQLite**. The design depends on `CHECK` constraint
semantics, revoked `UPDATE`/`DELETE` grants, Row-Level Security, `NUMERIC` precision,
`FOR UPDATE SKIP LOCKED`, and advisory locks — none of which SQLite has, so a suite passing
against SQLite would leave every one of those invariants unverified.

### Database roles

Three, not one, because [S0 §7.3](docs/specs/0-backend-foundation-design.md) makes bypassing
Row-Level Security a *credential* boundary rather than application discipline:

| Role | Used by | `BYPASSRLS` |
| --- | --- | --- |
| `trueup_owner` | Migrations only | no |
| `trueup_app` | The web API | **no — structurally incapable of cross-tenant reads** |
| `trueup_worker` | Jobs and the outbox worker | yes, by design |
| `trueup_chat_readonly` | S11's chat assistant tool calls only | no — and granted no table access at all except `SELECT` on the curated chat views (ADR 19) |

## Contributing

Read [`CLAUDE.md`](CLAUDE.md) and [`backend/CLAUDE.md`](backend/CLAUDE.md) first. Work on a
`feature_*`, `bugfix_*`, or `patch_*` branch, and ship tests with every behaviour change.

Update [`CHANGELOG.md`](CHANGELOG.md) and [`DECISION-LOG.md`](DECISION-LOG.md) **in the same commit
as the work they describe**. A decision log assembled retrospectively is worth nothing.
