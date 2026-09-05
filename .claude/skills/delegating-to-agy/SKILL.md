---
name: delegating-to-agy
description: Use when a Trueup backend implementation, refactor, test-writing, or debugging slice should be handed to the agy CLI instead of built in this session — parallel capacity beyond the in-session agents, or a problem worth a second model's independent take.
---

# Delegating to Agy

## Overview

`agy --print` is a co-equal implementer alongside the in-session `backend-engineer` subagent — and
full-stack: it can take a `backend/` (Flask) or `frontend/` (React) slice. It writes real files to
this repo, but **needs a one-time permission setup or it silently does nothing** — see below.
Verified against this project 2026-09-05 on a backend baseline run; the frontend rules below are
sourced from `frontend/CLAUDE.md` directly, not from an observed run.

## One-time setup (do this before the first delegation)

`agy --print` cannot use any tool non-interactively — not even reading a file — without allow-rules
in `~/.gemini/antigravity-cli/settings.json` (**not** `~/.gemini/settings.json` — a different file
with the same-looking name). Rules match by **literal string prefix only** — `*`/`**` suffixes do
not work as globs and will silently fail to match. Verified working:

```json
{
  "permissions": {
    "allow": [
      "read_file(/Users/badrinarayanan/Codes/projects/Trueup/)",
      "write_file(/Users/badrinarayanan/Codes/projects/Trueup/)",
      "command(*)"
    ]
  }
}
```

`read_file`/`write_file` are scoped to this repo's path prefix — genuinely narrower than
`--dangerously-skip-permissions`, which this skill never uses. `command` cannot be scoped this way
without enumerating every command name a delegate might reach for (`ls`, `grep`, `uv`, `ruff`,
`mypy`, a coverage tool); `command(*)` is the accepted trade-off, bounded by file access still
being repo-scoped. If a run fails with `"<tool>" permission ... auto-denied`, add that exact tool
name to `allow` and retry — the error names the tool.

## The command

```sh
agy --model gemini-3.1-pro-high --effort high --mode accept-edits --print "$(cat prompt.md)"
```

Every command and path in this skill is relative to the **Trueup repo root**
(`/Users/badrinarayanan/Codes/projects/Trueup`) — run from there, and confirm `pwd` first if a
prior command in the same shell may have `cd`'d elsewhere (shell state persists silently).

`gemini-3.1-pro` alone is **not** a valid model — `agy models` lists only `gemini-3.1-pro-high` and
`gemini-3.1-pro-low`; `--effort` does not resolve a bare name. Build `prompt.md` from
**`prompt-template.md`** in this directory before every delegation.

## Prompt contract

Same shape as `delegating-to-codex`: task + owning spec section → files owned → files forbidden →
the gate → the report shape, with `backend/CLAUDE.md` and the owning spec section **inlined** via
`$(cat ...)`/`$(sed -n ...)` — the baseline run below never read either on its own initiative.

## Searching this project

**Backend**: owning spec section → its ADR → `requirements.md` FR/NFR → `app/core/` → `rg` the
four test layers first. **Frontend**: `frontend/CLAUDE.md`'s Structure table → existing
`src/features/`/`src/components/`/`src/hooks/` for a pattern → the component's colocated test
file, if one exists — no `docs/specs/`/ADR trail for frontend yet.

## Non-negotiables

Never `git` anything — the orchestrator commits, after review. Never edit `docs/`. Never touch or
log `.env`. Never `uv add`/`npm install` without asking (frontend's one pre-authorized exception
is in `prompt-template.md`). Never weaken a test, type, or constraint to pass. Follow
SOLID/DRY/KISS exactly as `backend/CLAUDE.md` or `frontend/CLAUDE.md` states them — both are
pasted into every prompt. **Never leave an AI/agent attribution mark anywhere** — no "Generated
by", "Co-Authored-By", model name, or similar, in a code comment, docstring, or any file content
(root `CLAUDE.md`'s no-attribution policy, extended here since git is already forbidden above).

**Red flags in a completion report:** "tests pass" without naming which layers/commands ran
(backend: `mypy --strict`/`ruff check`/`lint-imports` by name; frontend: `npm run lint`/
`npm run build`/`npm test` by name); `unittest.mock.Mock` in a backend test (real fakes behind
`Protocol`s only); a test with no real assertion; any attribution mark in a diff.

## Required report shape

Every file changed, with why. Gate output verbatim. Which spec/ADR section this implements.
Decisions the spec didn't cover. Anything to double-check.

## Verify, do not trust

Apply `superpowers:receiving-code-review`'s discipline to the report: restate the claim, check it
against `git diff`, never respond performatively.

1. Re-run the gate yourself. Backend, from `backend/`: `uv run pytest -q && uv run mypy --strict
   app && uv run ruff check app tests && uv run lint-imports`. Frontend, from `frontend/`:
   `npm run lint && npm run build && npm test`.
2. Read the whole diff, not the report's summary — including a check for any attribution mark
   left in the changed files.
3. Only then stage and commit — only the orchestrator commits.

## Common mistakes

| Observed 2026-09-05 baseline | Fix |
| --- | --- |
| 9 `mypy --strict` failures: test functions missing `-> None` | Prompt requires the real `mypy --strict` pass, not just green `pytest` |
| `DbRole.APP == "app"` — mypy flags comparing a `StrEnum` to a raw string | Compare via `.value`; never compare a `StrEnum` member to a literal directly |
| Used `unittest.mock.Mock` | Forbidden — real fakes behind `Protocol`s only (S0 §11) |
| A test calling a `Protocol`'s `...` body just to pad coverage, asserting nothing real | Report must justify each test by the behavior it verifies |
| No docstrings; unsorted imports (`ruff I001`); only unit tests, never `lint-imports` | Full four-command gate, verbatim, is a required report field |
