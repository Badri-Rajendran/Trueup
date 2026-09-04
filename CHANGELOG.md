# Changelog

## Unreleased

- Gap review: add FR-37–48, NFR-13–14, and ADRs 9–12, closing 13 gaps found in a full doc re-read
  (wash sales, order-hold release, market holidays/timezone, and others). Add S10 (performance fees,
  promoted from stretch scope). Scope Stripe to KYC + fee billing only — rejected as a Plaid
  replacement since Alpaca requires Plaid-linked ACH for funding.
- Add `requirements.md` and link it from `CLAUDE.md`; add a no-Claude-attribution policy bullet
  (session-overridable) to `CLAUDE.md`.
- Initial docs: add `requirements.md`, populate `architecture.md`, and record ADRs 1–8 (ledger,
  settlement, returns, tax lots, cash policy, restatement, orders, rebalancing). Add the S1 (ledger
  core) design spec.
- Rename ADR files `000N` → `N` and update all cross-references.
- Move design specs from `docs/superpowers/specs/` to `docs/specs/` to match the repo's doc
  convention; add it to `CLAUDE.md`'s source-of-truth list.
- Name the project Trueup in `CLAUDE.md`, add an "About Trueup" summary linking the brief, and fix
  the stale "insurance data" rule to "brokerage, or bank data."
- Restructure `CLAUDE.md` into Stack/Ways of working/PRs/CI-CD/Security/Testing/Documentation
  sections; declare the app production-grade and pin the stack.
- Replace the stub `backend/CLAUDE.md` with MVC layering, `uv` tooling, Pydantic, and DRY/SOLID/KISS
  rules.
- Rewrite `frontend/CLAUDE.md` with feature-based React folder structure and hook/state discipline.
- Align `docs/architecture.md` and `backend/CLAUDE.md` on the same controller/view/model mapping.
- Remove `CONTRIBUTING.md` (stale, contradicted `backend/CLAUDE.md`); fold its one rule into root
  `CLAUDE.md`.
- Add a Commands section to `backend/CLAUDE.md` and a Testing section to `frontend/CLAUDE.md` for
  standards that had no corresponding command.
- Add the missing SQLAlchemy stack row, pin Vitest, and remove a duplicate branch rule in
  `CLAUDE.md`.
- Add `docs/requirements/project-description.md` with the product brief.
