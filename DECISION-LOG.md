# Decision Log

Timestamped record of what was decided, what was assumed when no answer was available, and what was
deliberately cut. Written as the work happens, not assembled afterwards — each entry names the
commit that carried it, and `git log` corroborates every date below.

**Distinct from [`docs/decisions/`](docs/decisions/)**, which holds the ADRs. An ADR answers *why
the architecture is shaped this way* and is a permanent design record. This log answers *what was
decided, assumed, or cut, and when* — including the many choices too small for an ADR, and the ones
that are not architecture at all. Entries reference ADRs where one exists; the ADRs carry no date
field of their own, so the date lives here.

Newest first. Times are local (America/Los_Angeles).

---

## Decisions

### 2026-09-05 — S9 build includes `/portfolios/models` and `/portfolios/assignment`

- S9's own spec text (`docs/specs/9-rebalancing.md`) never mentions an HTTP surface — only schema +
  services + the monthly job. `docs/specs/8-surfaces.md` §3, written later, lists
  `/portfolios/models` (GET) and `/portfolios/assignment` (GET, POST) with **"Owning spec: S9 §3"**
  — so these routes are S9's own domain per the surfaces spec's own attribution, not a pull-forward
  of S8's unbuilt work. Confirmed with the user before dispatch (offered "S9 spec's own scope only"
  vs. "also build the assignment endpoint now"; user chose the latter) since S9's document text
  alone reads as schema/mechanism-only.
- `rebalance-engineer` builds both routes as part of this wave, following S8 §3's one-line contract
  (method + purpose) since S8 gives no field-level schema — request/response shapes are the
  engineer's own design, consistent with this project's existing view/schema conventions.
- Model portfolio composition (real securities/weights for the four models) remains explicitly out
  of scope — a business/investment-committee decision `docs/specs/9-rebalancing.md` itself declines
  to invent. Test fixtures use placeholder weights only.

### 2026-09-05 — ADR 19 corrected: `security_invoker` views are incompatible with a zero-grant chat role

- **Escalated by `chat-engineer` before writing the S11 safety-perimeter migration**, verified
  independently against current Postgres docs before deciding: a `security_invoker = true` view
  checks the *invoking role's* permissions against the view's own underlying base tables, so
  `chat_readonly` would need a direct `GRANT SELECT` on `posting`/`journal_entry`/etc. just to use
  the curated views — contradicting ADR 19's "no grant on anything else" and defeating its own
  decisive test (permission-denied, not filtered, on a raw-table query).
- **Fix**: views are owner-executed (Postgres's default, no `security_invoker` clause) with the
  tenant scope baked directly into each view's own `WHERE` predicate, keyed on the same
  `app.role`/`app.customer_id` session GUCs the `UnitOfWork` and existing RLS policies (ADR 17)
  already use. Same governing property (database-enforced, session-identity-driven isolation, never
  the model's behavior), different mechanism. `chat_readonly`'s grants are unchanged: views only,
  zero base-table access.
- [ADR 19](docs/decisions/19-read-only-sql-tool-safety-perimeter.md) and
  [the S11 spec §4.1/§7](docs/specs/11-nl-query-assistant.md) updated in place to reflect the
  corrected mechanism — recorded as a correction since no code had shipped against the original text.

### 2026-09-05 — Wave 5 close-out (S5 tax lots and corporate actions)

- **Escalation, overridden**: `taxlot-engineer` initially left `LotConsumptionService` unwired
  from `AlpacaTradeUpdateHandler.handle()` to avoid breaking an existing S3 test outside its file
  boundary (`tests/integration/test_alpaca_trade_update_handler.py` seeded a dangling
  `security_id` with no backing row). Overridden: unwired would ship S5 as dead code the running
  app never calls, defeating the MVP push's own point. Directed to wire it for real and extend
  that one test's own fixture (add the new tables, insert a real `security` row) instead — a
  fixture fix, not new test-writing, so it doesn't conflict with the S5+ testing pivot. First
  report back claimed this was done but hadn't actually made the change (verified directly:
  no reference to lot consumption in the handler); sent back a second, firmer correction before
  the real wiring landed. Independently verified via full diff read + fresh gate run (mypy/ruff/
  lint-imports, migration round-trip, full pytest) before commit, per this session's standing
  discipline of never trusting a teammate's self-report.
- **`OrdersUnitOfWork` composition changed**: was `(IdentityUnitOfWork, LedgerUnitOfWork,
  OpsUnitOfWork)`, now `(IdentityUnitOfWork, LotsUnitOfWork, MarketDataUnitOfWork)`. Not a
  reduction — `LotsUnitOfWork` itself composes `LedgerUnitOfWork` + `OpsUnitOfWork`, so every
  repository the old bases exposed is still present transitively; `MarketDataUnitOfWork` is new,
  needed for the `MarketClock`/`calendar_cache` a fill's lot-opening now requires.
- **`lot_consumption.sale_date`** added beyond S5 §3.2's literal column list — the wash-sale
  algorithm (§5) needs a sale date and nothing else in the schema carries one.
- **`designation_window_closes_at`** computed from settlement date only, not
  `min(settlement, confirmation)` per ADR 4 literally — no S7 custodian-confirmation channel
  exists yet to feed the other half. Documented as a safe upper bound in the model; tightens once
  S7 exists. Not blocking, since it only ever widens the provisional window, never narrows it.
- **Specific-ID lot designation** is implemented in `LotConsumptionService.consume()`'s override
  branch but nothing produces `designated_lot_ids` yet — no `Order`/controller field exists for an
  investor to elect specific lots. Accepted as forward-compatible dead branch; the full ADR-4
  designation-event mechanism waits for a caller.

### 2026-09-05 — Wave 4 close-out (S2 funding, S3 orders, S4 valuation) and MVP pivot for S5+

- **`current_user` DetachedInstanceError (found during Wave 4, fixed on `main`)**: `Session.rollback()`
  (called by `UnitOfWork.__exit__` on any non-committed transaction — a deliberate "never commit
  implicitly" guarantee) expires every loaded attribute on tracked objects regardless of
  `expire_on_commit`; the follow-on `session.close()` then detaches the object, so any later
  attribute read (`current_user.id`, `Staff.role`) raised `DetachedInstanceError` on every
  authenticated request past login. Fixed once, at the actual call site
  (`app/controllers/api/auth.py::load_user`), by `session.expunge()`-ing the principal *after* the
  `UnitOfWork` block obtains it, immediately before returning it to Flask-Login. **Not** fixed
  inside `app/services/identity/auth.py`'s shared `find_principal_by_id`/`find_principal_by_email`
  — a first attempt did that and broke `mfa_enroll`'s fetch-then-mutate-then-commit pattern (2 test
  regressions), reverted. The 4 duplicate `_authorize_customer_id`/`_resolve_customer_id`
  workarounds Wave 4's engineers each independently wrote around this bug (in `identity.py`,
  `funding.py`, `orders.py`, `valuation.py`) are now redundant dead code — not yet removed;
  functionally harmless, flagged for cleanup whenever those files are next touched.
- **Funding eligibility-check ordering bug, fixed**: `DepositService.initiate`/
  `WithdrawalService.initiate` acquired `customer_cash_lock` *before* checking
  `kyc_status`/`account_approval_status`, so an ineligible customer got a 500
  (`CustomerCashLockMissingError`, since the lock only exists once
  `AccountApprovalService` has approved the account) instead of the intended 422
  (`FundingNotEligibleError`). Reordered: eligibility check, then bank-link check, then lock
  acquisition — the lock is only ever reached once both approvals hold.
- **Test-fixture bug, fixed**: `tests/api/test_valuation_api.py`'s per-table
  `create()`/`drop()` teardown loop dropped `daily_close` and `market_calendar_cache` — two tables
  sharing the native-Postgres `market_data_source` enum — in an order where SQLAlchemy's per-table
  drop event tries to drop the shared enum type while the other table still references it
  (`DependentObjectsStillExist`). Fixed to match the pattern already established in
  `tests/integration/test_valuation_service.py`: raw `DROP TABLE IF EXISTS` for teardown, never
  `Table.drop()`, for any table set sharing a native enum.
- **Known, disclosed, not fixed**: `tests/api/test_orders.py` creates `order`/`approval_hold` in a
  **session-scoped** autouse fixture (alive for the whole pytest session), while
  `tests/integration/test_account_approval_service.py` and
  `test_account_customer_receivable_role.py` each drop `customer` in their own **function-scoped**
  fixture. Since `order`/`approval_hold` FK to `customer` and outlive it, the full suite run hits
  `DependentObjectsStillExist` at teardown of those two integration files (test bodies themselves
  all pass — 501 passed, 5 teardown-only errors). Root cause identified, not fixed: a genuine
  fixture-scope mismatch between two independently-built test files, not an application bug.
  Deprioritized per the MVP pivot below.
- **MVP pivot for S5 onward**: for S5–S12, tests are no longer written alongside each feature;
  `mypy --strict`, `ruff`, and `lint-imports` remain mandatory gates (cheap, catch real defects,
  cost nothing extra). `TDD`/"test-first" language removed from `backend/CLAUDE.md` and the
  `backend-engineer`/`qa-tester` agent definitions — tests are still expected eventually, just not
  as a per-feature blocking discipline while the backend races toward a working MVP.
- **S5 (tax lots) / S6 (restatement) / S7 (reconciliation) dispatched in parallel** despite S6's
  real dependency on S5's lot-tracking interface — accepted risk of an S6 rework pass once S5's
  actual shape is known, in exchange for wall-clock speed (explicit user choice over the
  dependency-respecting sequential alternative).

### 2026-09-05 12:25 — When a customer's cash accounts and cash-lock get created (S1 §3.5)

- **Escalated by two teammates independently** — `funding-engineer` (S2) hit it needing to post a
  deposit; `ledger-engineer` (S1, already done and idle) reviewed the proposal from the spec's own
  side rather than staying silent, and flagged the precedent this sets for S3's own account
  bootstrap. Neither guessed; both escalated.
- S1 §3.5 said `customer_cash_lock` is "one row per customer, created with the customer" — read
  literally, at registration. Nothing can address a cash-lock row or `cash`/`customer_equity`
  accounts before funding is even possible, and funding is gated on `kyc_status = approved AND
  account_approval_status = approved` (S2 §3.1) — creating them at registration leaves permanent,
  unused rows for every customer who never completes approval.
- **Resolved: `AccountApprovalService` creates `customer_cash_lock` and the customer's `cash`/
  `customer_equity` accounts atomically, in the same transaction that flips
  `account_approval_status = approved`** — the simulated custodian-account-open event (ADR 21) is
  the natural point a custodial cash relationship begins. S1 §3.5 amended to match.
- **Explicitly not the pattern for `position_units`/`position_cost` accounts** — those are
  per-security, not a per-customer singleton, and bootstrap lazily on a customer's first trade
  against that security instead (S3's job). Two account kinds, two lifecycles, both by design —
  recorded now so S3 doesn't have to re-litigate the same question.
- Not an ADR: a schema-lifecycle clarification within S1/S2, not a new cross-cutting architectural
  direction comparable to ADR 21-23's provider choices.

### 2026-09-05 11:59 — Frontend spec, first pass: structure + design system

- Dispatched alongside Wave 3 as two more named teammates, `frontend-architect` and
  `frontend-designer` — genuinely parallel, since a spec has no dependency on backend
  implementation progress. Design only, no code, no `npm install`.
- `docs/specs/frontend/structure.md` (`frontend-architect`): route map, component hierarchy,
  state/hook boundaries, `services/` API contracts, named loading/empty/error states, testing
  strategy — every route grounded in `8-surfaces.md`'s actual endpoint table, none invented.
- `docs/specs/frontend/design-system.md` (`frontend-designer`), plus a
  [verified mockup artifact](https://claude.ai/code/artifact/708c1cba-9474-42cb-b099-d9deb4bec2a5):
  a "ledger, not dashboard" visual system — 5 chromatic tokens, WCAG contrast measured not
  asserted, every domain pattern traced to the specific ADR/FR it serves (restatement,
  withdrawable-vs-investable, simulated approval, break aging, privileged actions,
  stale-price-vs-holiday) rather than invented as decoration.
- The two teammates coordinated directly by name rather than routing through `main` — `structure.md`'s
  component inventory shaped `design-system.md`'s per-component specs; three load-bearing notes
  `frontend-architect` flagged (equal-weight cash figures, a shared privileged-action pattern, the
  stale-price-vs-holiday distinction) were folded back into the design system before either called
  it done.
- One real gap surfaced this way, not by either agent-produced documentation review: see the
  `GET /admin/customers?query=` entry below.
- Committed separately from Wave 3 — a design artifact, not a wave deliverable, with zero
  dependency on backend progress.

### 2026-09-05 11:45 — Add `GET /admin/customers?query=` (S8)

- **A sixth gap, found by a `frontend-architect` teammate designing the frontend spec, not by
  either agent-produced documentation review.** Every existing `/admin/*` route requires a
  `customer_id` the adviser must already have (via a reconciliation-break row, or a direct ID) —
  there was no way to reach a customer with no open break, e.g. answering a support call. Resolved
  by the user: added a search/directory endpoint to S8 §4, paginated, matching email (name once S2
  carries one). Backend implementation is S8/S2 territory, deferred to whichever wave builds the
  adviser surface — not blocking Wave 3 (S1) or the frontend spec, which can now include a
  directory screen.

### 2026-09-05 12:01 — Wave 3 complete: S1 ledger & units core

- **First real Team dispatch this session** — three named teammates (`ledger-engineer`,
  `frontend-architect`, `frontend-designer`) spawned via the `Agent` tool's `name` parameter,
  messaging each other and `main` directly, rather than CLI delegation or one-shot subagents.
  `ledger-engineer` built S1 alone, deliberately not parallelized — the build plan's own reasoning
  (highest correctness risk, everything downstream depends on it) held.
- **S1 ledger built in full**: `account`/`journal_entry`/`posting`/`settlement_obligation`/
  `customer_cash_lock`, the `DEFERRABLE INITIALLY DEFERRED` zero-sum trigger (ADR 17), the
  `posting_before_insert` customer_id-denormalization + dimension-validation trigger (both DDL
  events bound to the table's own SQLAlchemy lifecycle, not only the migration — the pattern
  established in Wave 2), revoked `UPDATE`/`DELETE` on `journal_entry`/`posting` from **both**
  runtime roles (not just `trueup_app` — jobs never mutate the ledger either; a correction is
  always a new row), RLS on `account`/`posting`/`customer_cash_lock`, `PostingService`,
  `CashPolicyService` (including `unsettled_deposit_proceeds`, the term added earlier this
  session). 331 tests, independently verified from a completely fresh container: `mypy --strict`
  clean, `ruff` clean, `lint-imports` 5/5, migration round-trip clean.
- **The zero-sum-at-COMMIT test, read in full, not just trusted for its pass count**: inserts a
  deliberately unbalanced posting pair directly (bypassing `PostingService`), asserts `flush()`
  does not raise (the trigger is deferred) and `commit()` does — the exact test S1 §7 item 1 warns
  a naive rollback-only fixture would make pass vacuously. Uses `db_committing`, correctly.
  **Both RLS directions verified the same way as `customer`'s in Wave 2**: raw `select(Posting)`/
  `select(Account)`, no repository filter, under `DbRole.APP` — a `customer`-role session cannot
  see another customer's rows even with the app-layer guard bypassed; `adviser` and `admin` can,
  tested as two separate cases so a policy bug scoped to one role literal wouldn't hide.
- **`superseded_by` direction confirmed**, independently, the same conclusion reached earlier this
  session reviewing the same ambiguity: the *new*, superseding entry carries the pointer backward
  — required by `journal_entry` being append-only (the original can never be updated) and by S1
  §7 item 3's explicit round-trip requirement. `ledger-engineer` flagged the same tension without
  seeing this session's earlier resolution and landed on the identical reading.
- **`journal_entry`/`settlement_obligation` deliberately get no RLS policy** — neither carries a
  `customer_id` in S1's own schema (an entry can span a customer's accounts and a house account),
  matching the precedent already set for `inbound_event`/`job_outbox`/`job_run` in Wave 2.
  Per-customer reads compose through `posting`/`account`, which do carry it.

### 2026-09-05 10:54 — Wave 2 complete: ops spine + security/auth (S0 §6/§7/§9)

- **CLI delegation abandoned mid-wave, in-session subagents finished it.** Wave 2's two tracks were
  first dispatched to `delegating-to-codex`/`delegating-to-agy`. Track C (codex, ops spine) landed
  cleanly. Track D (agy, security/auth) did not: `claude-opus-4-6-thinking` hit an account-level
  quota (~2h reset) on the first real attempt; the `gemini-3.1-pro-high` fallback then failed twice
  with `Error: timeout waiting for response`, after leaving a stray, out-of-scope script
  (`backend/fix_db.py` — `DROP SCHEMA public CASCADE` against the dev DB) that was found and
  deleted, never committed. User redirected: finish the wave with the in-session
  `backend-engineer`/`qa-tester` subagents instead, three segments dispatched in parallel —
  finishing Track D, fixing a Track C defect, and independently QA-verifying Track C. Recorded as a
  fact worth keeping, not a reason to revisit the agy model choice itself (that decision stands).
- **A stray subagent deleted `.claude/skills/` entirely, mid-run, outside its stated scope.**
  Discovered via `git status` showing the whole directory as deleted. Fully recoverable (git-
  tracked, committed at `bab5148`) via `git checkout`, but that recovery silently reverted this
  session's earlier, **never-committed** edits repointing `delegating-to-agy` at
  `claude-opus-4-6-thinking` — those edits had to be reconstructed and reapplied by hand from this
  session's own record. No other files were affected (checked repo-wide). Root cause not fully
  isolated — the two `backend-engineer` prompts never referenced `.claude/` and were scoped
  strictly to files under `backend/`, and per-agent transcripts are not something the orchestrator
  reads directly — but Segment 1's dispatch (36 minutes, 242 tool calls) is the most plausible
  source given its scope and duration. Flagging the exposure, not assigning certain blame: an
  agent with unrestricted tool access can affect files well outside its assigned scope, and nothing
  currently guards against it beyond post-hoc `git status` review. Worth a follow-up decision on
  whether agent dispatches should be scoped away from `.claude/` more forcibly.
- **Five real defects found and fixed during independent verification, none from either
  subagent's own self-report:**
  1. Track C's ops-spine Alembic migration had **empty `upgrade()`/`downgrade()` bodies** — codex's
     sandbox couldn't reach Postgres to autogenerate, and it never went back to hand-write them
     despite reporting that it would. Regenerated correctly using live DB access the orchestrator
     has and the sandbox doesn't.
  2. Postgres's `date_trunc()` is `STABLE`, not `IMMUTABLE`, so `job_run`'s monthly partial unique
     index (as S0 §9 itself specifies it) cannot be built directly — a real gap in the spec text,
     not an implementation mistake. Fixed with a small `IMMUTABLE` SQL wrapper function
     (`job_run_month_start`), attached to both the migration and the model's own DDL lifecycle (a
     `before_create` event) so `Base.metadata.create_all()` — the pattern every integration test in
     this repo uses instead of running migrations — gets it too, matching the same pattern used for
     `Customer`'s RLS policy (below).
  3. The identity migration's RLS policy relied on Postgres evaluating `OR` left-to-right, which
     Postgres does not guarantee — an adviser/admin session (empty `app.customer_id`) could hit a
     bad `''::uuid` cast on some evaluation orders. Fixed with `NULLIF(..., '')` (found and fixed by
     the `backend-engineer` segment, independently confirmed here).
  4. `KycStatus`/`AccountApprovalStatus` on `customer` were bare `enum.Enum`, not `StrEnum` — the
     identical footgun (members compare `False` against a string literal without `.value`) the
     `backend-engineer` segment had just found and fixed on `StaffRole` for the same reason. Fixed
     before S2 gives these columns their first real reader.
  5. A genuine test bug in `test_ops_spine.py`: hardcoded `now = datetime(2026, 9, 5, tzinfo=UTC)`
     (midnight UTC) is earlier than the row's actual `next_attempt_at` (server `now()` at insert,
     i.e. the real time of day) — `claim_next`'s `<=` filter correctly excluded the row per what
     was written, incorrectly per what the test meant. Fixed to `datetime.now(UTC)`.
  Three of the three fixed by the orchestrator directly (1, 2, 5) came from independently re-running
  the full gate from a completely fresh container three times, not from trusting either subagent's
  reported pass count.
- **`BaseRepository.customer_id_column` made optional**, replacing a placeholder `.id` three ops
  repositories (`inbound_event`, `job_outbox`, `job_run`) had to pass just to satisfy a required
  constructor argument, for tables with no customer identity at all. `_tenant_scoped()` now raises
  a clear error if called on a repository configured without one, instead of silently building a
  meaningless `WHERE id = customer_id` filter.
- **`staff` table added (S0 §7.2), separate from `customer`** — a fifth gap, found independently of
  either agent-produced documentation review, while designing Track D's concrete auth routes: no
  spec anywhere defined where adviser/admin accounts live. `customer` has ledger accounts and a KYC
  lifecycle; staff has neither. Both satisfy one `AuthPrincipal`-shaped interface.
- **Full gate, independently verified, three consecutive runs from a completely fresh container**
  (`docker compose down -v && up -d`, not just a reused one): `pytest -q` 291 passed, `mypy --strict
  app` clean, `ruff check app tests` clean, `lint-imports` 5/5, `alembic upgrade head → downgrade
  base → upgrade head` round-trips clean on both the dev and test databases.

### 2026-09-05 09:25 — Four S0/S1 gaps closed before Wave 2

Found independently by cross-checking two agent-produced documentation reviews
(`docs/analysis/documentation-review-2026-09-05.md` from codex,
`~/.gemini/antigravity-cli/brain/.../trueup-docs-analysis.md` from agy) against the actual spec
text — not trusted from either review without verification. Two of the four "Critical" items in
codex's review were real; one (`superseded_by`'s wording) turned out to be a documentation
ambiguity, not a contradiction, once read against ADR 1's actual direction (the *new*, superseding
entry carries the pointer backward — insert-only, consistent with the revoked `UPDATE` grant). A
fourth gap — unrelated to either review, found while designing Wave 2 Track D's concrete auth
routes — surfaced independently: no spec anywhere defines where adviser/admin accounts live.

- **S1 `posting` gets a `customer_id` column and a `BEFORE INSERT` trigger.** S0 §7.3's RLS policy
  example filtered `posting` directly on `customer_id`, a column that did not exist — `posting`
  only had `account_id`, and `customer_id` lives on `account`. Same root cause blocked the
  dimension `CHECK`: "the non-null column must match the target account's dimension" is a
  cross-table condition a plain `CHECK` cannot express. One trigger,
  `posting_denormalize_and_validate()`, does both jobs: copies `customer_id` from the account
  (never writable by application code) and rejects a dimension mismatch. Coexists with ADR 17's
  existing deferred zero-sum trigger on the same table — different trigger, different timing,
  different job.
- **S1 `investable()` gets `+ unsettled_deposit_proceeds(customer)`.** The formula had a term for
  one unsettled inflow (`unsettled_sale_proceeds`) but not the other. S2 states plainly that a
  deposit is investable immediately, before settlement confirms — the formula as written would
  have made a fresh deposit uninvestable until T+1, contradicting S2 outright.
  `withdrawable(customer)` deliberately gets no equivalent term — ADR 5 already states unsettled
  proceeds of any kind are investable but never withdrawable.
- **S0 §7.3's RLS example annotated**, not changed in substance: `posting.customer_id` is now a
  real, trigger-populated column, so the example is accurate as written — the annotation explains
  why `posting` needed denormalization when most customer-scoped tables carry their own
  `customer_id` natively.
- **New `staff` table (S0 §7.2), separate from `customer`.** S0 §7.2 requires three roles
  (`customer`/`adviser`/`admin`) with mandatory adviser TOTP MFA, but the only user table any spec
  defined was S2's `customer` — no `role` column, and nowhere else names a home for adviser/admin
  accounts. Two tables, not one with a nullable `role`/`totp_secret`: a customer has ledger
  accounts and a KYC lifecycle; staff has neither. `staff(id, email, password_hash, role,
  totp_secret_encrypted, created_at)`, `totp_secret_encrypted` via `EncryptedText`/ADR 23. Both
  tables satisfy one `AuthPrincipal` `Protocol` so Flask-Login's loader and `@requires_role` don't
  need to know which table a principal came from. User's own call, via `AskUserQuestion`, over the
  alternative (one table, nullable columns per role).

All four amend `docs/specs/0-backend-foundation-design.md` and
`docs/specs/1-ledger-units-core-design.md` directly, ahead of Wave 2/3 rather than inside their
implementation — same discipline as the four table-schema gaps closed in Wave −1.

### 2026-09-05 08:20 — agy repointed to Claude Opus 4.6

- **`delegating-to-agy` now runs `claude-opus-4-6-thinking`, not `gemini-3.1-pro-high`.** The
  skill's own "only two models exist" claim was false: `agy models` lists 15 across three
  families (Gemini 3.6/3.7/3.8 Flash, Gemini 3.1 Pro, `claude-sonnet-4-6`,
  `claude-opus-4-6-thinking`, `gpt-oss-120b-medium`). Corrected to the real constraint: effort is
  part of the Gemini model name (`-high`/`-low`); the Claude and `gpt-oss` entries take no
  `--effort` flag at all and error if one is passed.
- **Consequence, stated rather than glossed:** agy now runs the same model family as the
  orchestrating session, so it is no longer a cross-family second opinion — only parallel capacity
  and an independently-run second implementation. `delegating-to-codex` (GPT-5.6) keeps the
  cross-family role.
- **Re-baselined rather than relabelled.** The skill's Common Mistakes table was Gemini's observed
  failure profile; carrying it forward under a different model would have been fiction. Re-ran the
  skill's own RED→GREEN cycle against a fresh gap (`app/core/logging.py` had no test file — the
  prior gap, `app/core/db.py`, was already closed): Opus 4.6 passed the full gate clean on both the
  baseline and the independent verification run (222 tests, `mypy --strict` clean, `ruff` clean,
  `lint-imports` 5/5), with no `unittest.mock`, no attribution mark, and a self-reported judgment
  call (importing a private `ContextVar` into the test) that held up under review. The table now
  keeps both baselines side by side rather than merging them, since a Gemini-specific failure
  (e.g. the `StrEnum`-vs-string bug) has no reason to reproduce on a different model family.
- Added `backend/tests/unit/test_logging.py`, the verified output of the re-baseline: correlation-
  ID generation/propagation, the structlog processor's key-presence contract, renderer selection,
  and logger usability (S0 §7.4, OWASP A09).

### 2026-09-05 — Delegation skills for codex and agy

- Added `.claude/skills/delegating-to-codex/` and `.claude/skills/delegating-to-agy/`, so either
  CLI can take a Trueup implementation slice as a co-equal implementer alongside the in-session
  `backend-engineer`, never via git.
- **`agy --print` cannot use any tool non-interactively — not even reading a file — without allow-
  rules in `~/.gemini/antigravity-cli/settings.json`** (not `~/.gemini/settings.json`, a different
  file with the same-looking name). Rules match by **literal string prefix only**: `read_file(/path/)`
  and `write_file(/path/)` work; `read_file(/path/**)` and `read_file(/path/*)` silently fail to
  match. Found empirically after five failed variants; the working form has no glob characters at
  all. `gemini-3.1-pro` alone is also not a valid model name — only `-high`/`-low` suffixed forms
  exist in `agy models`.
- **`codex exec -s workspace-write` sandboxes network access.** A verification run confirmed codex
  cannot reach PostgreSQL on `localhost:5433` from inside that sandbox — it correctly reported the
  connection failure rather than claiming a false pass. It can run `mypy --strict`, `ruff check`,
  `lint-imports`, and pure `tests/unit/` tests; it cannot run the DB-backed test layers. The
  orchestrator running the full gate independently is therefore structural for codex, not only
  discipline.
- Both skills tested per `writing-skills`' RED→GREEN cycle: a naive baseline run against a real gap
  (`app/core/db.py` had no test file) surfaced concrete failures — codex never ran `lint-imports`
  and scoped itself to `tests/unit` only; agy produced 9 `mypy --strict` failures (untyped test
  functions), a `StrEnum`-vs-string comparison bug, `unittest.mock.Mock` instead of a real fake,
  and a coverage-padding test with no real assertion. Both skills were written against those
  specific failures, then verified: a second run through the actual skill template passed the full
  gate (213 tests, `mypy --strict` clean, `ruff` clean, `lint-imports` 5/5) for both CLIs, with agy
  self-correcting the exact `StrEnum` bug from its own baseline once the skill's non-negotiables
  named it.

### 2026-09-05 00:12 — S0 core vocabulary (`6d339af`)

- `Money`/`Units`/`Price` make dimension errors **static as well as runtime**: `Money + Units`,
  `Money * Money` and `Money == Units` fail `mypy --strict` in addition to raising `TypeError`, and
  no `float` can construct or scale any of them (ADR 16).
- **Added `Money / Units → Price`, amending S0 §4 and ADR 16 from one legal cross-dimension
  operation to two.** S3 §3.1's `average_fill_price` has no other route that does not unwrap to a
  bare `Decimal` — which is exactly the hole ADR 16 exists to close. The agent implementing money
  flagged this rather than inventing the operator; the spec was amended before the code shipped.
- `allocate()` splits pro-rata by largest remainder, so the leftover penny lands deterministically
  (non-negotiable #6).
- `UnitOfWork` takes tenant context **explicitly** rather than reading `flask.g`, so jobs and the
  outbox worker — which have no request context — share one transaction boundary.
- **Fixed a layering hole the contract had missed.** `app/core/uow.py` imported `app/extensions.py`,
  which S0 §3 forbids ("core imports nothing else under `app/`") but `import-linter` allowed,
  because the contract listed only the six layers. The contract now covers `app.extensions` and
  `app.config`; `DbRole` moved to `app/core/db.py` and the session factory is registered at startup.
  A weak contract that passes is worse than no contract, because it reads as proof.

### 2026-09-04 23:42 — Backend skeleton (`5f7ecb9`)

- **Three database roles, not one** — `trueup_owner`, `trueup_app` (no `BYPASSRLS`),
  `trueup_worker` (`BYPASSRLS`). S0 §7.3 makes tenant isolation a credential boundary; the web
  API's credential is now structurally incapable of a cross-tenant read regardless of any future
  request-handling bug.
- **Two test session fixtures on purpose.** `db_session` rolls back per test; `db_committing`
  really commits. S1's `DEFERRABLE INITIALLY DEFERRED` ledger-balance trigger only fires at COMMIT,
  so under a rollback-only fixture the test asserting it rejects an unbalanced entry would pass
  while proving nothing.
- **PostgreSQL on 5433 and Redis on 6380**, not the defaults — another project on the same machine
  already held 5432. Non-default ports permanently, so Trueup cannot be pointed at or mistaken for
  the wrong database.
- **A blank environment variable now reads as unset, not as a value.** Found by a smoke test:
  `.env.example` ships every optional credential as `KEY=`, and an empty string is not `None`, so
  `AZURE_KEY_VAULT_URL=` read as "Key Vault is configured" and startup tried to dial a vault at
  `""`. The same flaw would have read a blank `ALPACA_API_KEY_ID` as a real credential.
- `.gitignore` no longer excludes `frontend/src`, which would have silently dropped every new
  frontend file from future commits.
- Plain SQLAlchemy 2 rather than Flask-SQLAlchemy: S0 §5 puts the session inside the unit of work,
  and Flask-SQLAlchemy's request-scoped session fights that ownership.

### 2026-09-04 23:28 — Spec gaps closed; ADRs 22–23 (`91e9bdb`)

- **Four tables were referenced by FK or prose but had no schema** — `security`,
  `market_calendar_cache`, `sub_period_return`, `customer_cash_lock`. Each was added to the spec
  that owns its domain **before** any code, rather than invented inside an implementation.
- [ADR 22](docs/decisions/22-alpaca-trade-updates-websocket-intake.md): Alpaca fills arrive over a
  `trade_updates` websocket, not an HTTP webhook. The Paper Trading API chosen in ADR 21 has no
  webhook events at all — only Broker API does — so S3's `webhooks/alpaca_fills.py` could never
  have worked. Intake table, `execution_id` dedupe key and outbox hand-off are unchanged; only the
  transport differs.
- [ADR 23](docs/decisions/23-key-vault-envelope-encryption.md): Key Vault envelope encryption for
  `bank_link.plaid_access_token` and adviser TOTP secrets. Per-record AES-256-GCM data keys wrapped
  by an RSA key that never leaves the vault, with an in-process DEK cache so only cache misses
  cross the network.

### 2026-09-04 22:37 — Alpaca product choice (`08a6f64`)

- [ADR 21](docs/decisions/21-alpaca-paper-trading-not-broker-api.md): **Alpaca Paper Trading API,
  not Broker API.** Broker API requires an application and an open-ended approval wait before any
  sandbox access exists, incompatible with the timeline.
- **Consequence, stated rather than glossed:** FR-39's brokerage-side account-approval lifecycle is
  **simulated**, because this product has no per-customer onboarding verdict to wait on. NFR-12 is
  qualified accordingly in `requirements.md` — order placement, fills, positions and market data
  are genuinely live; only the approval verdict is not.

### 2026-09-04 21:23 — Production operations (`8ec31f9`)

S12 and [ADR 20](docs/decisions/20-observability-and-realtime-push.md): Azure Application Insights
for observability, SSE + Redis Pub/Sub for real-time push — no new vendor, reuses Redis.

### 2026-09-04 21:01 — Specs S2–S11 (`cb5b180`)

- Full design specs written for S2–S10 and S11, closing the gap where only S1 had one.
- Deferred parameters resolved: S9's drift band, S3's approval threshold, S2's limits, S7's
  custodian file format.
- **`FEE_RATE_PCT` deliberately left with no default** — a business decision, not one to invent in
  a spec.
- ADRs 18–19: OpenAI Agent SDK as the LLM vendor, and the read-only SQL tool's safety perimeter.

### 2026-09-04 17:42 — Backend foundation (`e480687`)

ADRs 13–17: Azure Container Apps Jobs over Celery (a broker holding in-flight financial work is a
second source of truth); layered architecture with repository and unit of work; server-side session
auth with mandatory adviser MFA; typed money value objects; a database trigger for the ledger's
zero-sum invariant plus role-aware RLS. Hot-path event draining was split onto an always-on worker
instead of cron, fixing FR-9's processing latency.

### 2026-09-04 14:30 — Requirements and ADR framework (`0acb2f8`)

48 FRs, 14 NFRs, ADRs 1–12. **Stripe scoped to KYC and fee billing only** — rejected as a Plaid
replacement, since Alpaca requires Plaid-linked ACH for funding.

---

## Assumptions

Made because no answer was available. Each names what changes if it turns out wrong.

| Assumption | If wrong |
| --- | --- |
| **No provider credentials yet** → real adapters *and* fakes built now; contract tests parametrize over both and auto-skip the real side until keys land. Nothing inside the application is mocked. | Nothing structural. The real adapters already exist; supplying keys flips the skipped tests on. |
| **`KYC_MAX_ATTEMPTS = 3`; deposit caps $25,000 per transaction, $50,000 per day.** Defensible engineering defaults, **flagged for compliance review against actual NACHA/ACH network limits before go-live** — not a compliance sign-off. | Settings change, no code or schema change. |
| **`ORDER_APPROVAL_THRESHOLD_USD = $10,000`**, with `> threshold` requiring approval and `<= threshold` not. The boundary is stated explicitly so it is not left to whichever comparison operator gets typed first. | Setting change. |
| **`inbound_event.signature_verified = true` for the Alpaca websocket**, on the strength of the authenticated TLS session: Trueup opens the connection to Alpaca's own host with its own key, so there is no per-message signature and no third party who could inject one. This differs from Stripe and Plaid, where an unauthenticated public endpoint makes the signature the only trust anchor. | The column's meaning would need splitting per source. Recorded in ADR 22 so the difference is never silent. |
| **Local `.env` generated for development** with a random `SECRET_KEY` and `LOCAL_CIPHER_KEY`; gitignored, containing only docker-compose credentials. Alembic cannot run without settings. | None — it is developer-local and never committed. |

---

## Cuts and deferrals

Deliberately not built. Each is a choice, not an oversight.

- **S5–S12 and the entire frontend** — outside the current S0–S4 slice.
- **The MCP agent surface (non-negotiable #5)** — **owed work, currently unscoped.** No FR in
  `requirements.md`, no spec, and no ADR covers it. Recorded here so it stops being invisible.
- **`Money / Price → Units`** — the remaining algebraic inverse. Nothing in S0–S12 needs it, and an
  untested operator on a money path is a liability rather than a convenience. Its absence is
  documented in the module so it reads as a decision.
- **Bounced-deposit collection and write-off policy** (S2 §9) — the resulting debt is recorded
  correctly as a `correction` entry against a `customer_receivable` account; recovering it is not
  designed.
- **Re-screening an already-approved customer against a later sanctions hit** —
  `requirements.md`'s own stated out-of-scope item.
- **Polling as a fill-delivery mechanism** — retained only as S7's morning reconciliation backstop,
  which is a reconciliation feature in its own right (non-negotiable #4). Non-negotiable #2 is
  satisfied rather than worked around.
- **Adding `Date:` fields to the 23 existing ADRs** — this log carries the dates instead, avoiding
  23 files of churn for the same traceability.

---

## Known inconsistencies, flagged not fixed

- **S0 §7.4 records "LLM Top 10: not applicable to v1 — no AI/LLM feature is in scope."** S11 and
  ADR 18 later added an OpenAI-backed assistant, so that line is now stale. Outside the S0–S4
  slice; left for a deliberate decision rather than edited in passing.
