# 14 — Layering: services/integrations/core added to MVC; repository + unit of work with a mandatory watermark

## Status

Accepted

## Context

`backend/CLAUDE.md` defines exactly three layers — controller, view, model — and directs
multi-entity rules into "their own module under `app/models/`." That has no natural home for two
things the design now needs: domain/application services (the cash-policy engine, TWR computation,
fee accrual) and provider adapters (Alpaca, Plaid, Stripe). Forcing both into `app/models/` would
make one layer responsible for entities, business rules, and HTTP clients to third parties — three
unrelated reasons to change, in tension with the Single Responsibility Principle root `CLAUDE.md`
already requires (SOLID). Separately, ADR 6 requires that which bitemporal watermark a read uses
"must be enforced at the query layer, not left to callers to remember" — a constraint that needs a
concrete data-access mechanism, not just a convention.

## Decision

### Extend the layers

`services/`, `integrations/`, and `core/` join `controllers/`, `views/`, `models/` as first-class
packages under `app/` (full layout in `docs/specs/0-backend-foundation-design.md` §3):

- **`core/`** — shared vocabulary (value objects, the unit-of-work, the base repository, the error
  hierarchy, security decorators). Imports nothing else under `app/`.
- **`models/`** — SQLAlchemy entities and one repository per aggregate. No business rules.
- **`services/`** — domain and application logic, one clear responsibility per class.
- **`integrations/`** — ports (`Protocol`s) and adapters. The only code that speaks HTTP to Alpaca,
  Plaid, or Stripe.
- **`controllers/` / `views/`** — unchanged in spirit: thin request handling, and response
  serialization via explicit schemas, never a raw entity dump.

Dependency direction, enforced in CI by `import-linter`: `controllers → services → models → core`,
and `services → integrations` only through `Protocol`s defined in `integrations/ports.py` — never a
concrete adapter import. This is Dependency Inversion in the SOLID sense: a service depends on an
abstraction it owns the shape of, not on a concrete Alpaca/Plaid/Stripe client.

### Repository + Unit of Work for persistence

- `UnitOfWork` is the transaction boundary — one per request, one per job step. Services receive
  repositories through it rather than holding a raw SQLAlchemy session.
- `BaseRepository` scopes every query by tenant and blocks mutation of append-only aggregates at the
  ORM layer, on top of S1 §6's revoked database grants.
- Any repository method reading a bitemporally-sensitive aggregate takes `as_of: Watermark` as a
  **required** keyword argument, with no default — omitting it is a type error caught before code
  ships, not a runtime figure quietly mislabelled as published.

## Consequences

- `backend/CLAUDE.md` is updated to describe six layers instead of three, and to add the dependency
  rule as a stated constraint rather than an implicit convention.
- Every service is unit-testable against a fake repository or a fake integration adapter with no
  database or network — required for the ports-and-adapters contract-test strategy in the foundation
  spec §11.
- A new provider (e.g. a second market-data vendor) is added by writing one adapter against an
  existing port, touching no service code — Open/Closed in practice, not just in principle.
- Slightly more ceremony per aggregate (a repository class in addition to the entity) than writing
  ad hoc queries inline — accepted as the cost of making ADR 6's watermark rule and NFR-1's
  append-only rule structurally enforced rather than remembered.

## Alternatives considered

- **Keep three layers strictly**, pushing services and adapters into `app/models/`. Rejected:
  `app/models/` would hold entities, business rules, and third-party HTTP clients simultaneously —
  a direct SRP violation, and it gives `models/` an import on outbound network calls that has no
  business being in an entity layer.
- **Nest services/integrations under `app/models/services/` and `app/models/integrations/`** to keep
  exactly three top-level directories. Rejected as cosmetic: the responsibilities are still distinct
  layers, and prefixing them under `models/` only obscures the dependency direction without changing
  it — worse for readability than naming the layers what they are.
- **Services hold `db.session` directly, no repository/unit-of-work.** Simplest, most familiar
  Flask-SQLAlchemy idiom. Rejected because ADR 6's watermark requirement and NFR-1's append-only
  requirement would then depend on every call site remembering to apply them correctly, forever —
  exactly the failure mode ADR 6 itself warns against ("an easy mistake to leave implicit").
