---
name: delegating-to-agy
description: Use when a Trueup backend implementation, refactor, test-writing, or debugging slice should be handed to the agy CLI instead of built in this session — parallel capacity beyond the in-session agents, or an independently-run second implementation to compare against.
---

# Delegating to Agy

## Overview

`agy --print` is a co-equal implementer alongside the in-session `backend-engineer` subagent — and
full-stack: it can take a `backend/` (Flask) or `frontend/` (React) slice. It writes real files to
this repo, but **needs a one-time permission setup or it silently does nothing** — see below.
Runs on `claude-opus-4-6-thinking` (see The command) — the same model family as the orchestrating
session, so treat agy as parallel capacity and an independently-run second implementation, not a
cross-family second opinion; `delegating-to-codex` (GPT-5.6) is the cross-family option. Verified
against this project 2026-09-05 on a backend baseline run; the frontend rules below are sourced
from `frontend/CLAUDE.md` directly, not from an observed run.

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
agy --model claude-opus-4-6-thinking --mode accept-edits --print "$(cat prompt.md)"
```

Every command and path in this skill is relative to the **Trueup repo root**
(`/Users/badrinarayanan/Codes/projects/Trueup`) — run from there, and confirm `pwd` first if a
prior command in the same shell may have `cd`'d elsewhere (shell state persists silently).

**No `--effort` flag with this model** — `agy` rejects it: `--effort is not supported for model
"claude-opus-4-6-thinking"`. Effort is only meaningful for the Gemini models, where it's baked
into the name (`gemini-3.1-pro-high`/`-low` — a bare `gemini-3.1-pro` is invalid for the same
reason); the Claude and `gpt-oss` entries in `agy models` take no `--effort` at all. Run `agy
models` to see the full, current list rather than trusting a name from memory — it has changed
before. Build `prompt.md` from **`prompt-template.md`** in this directory before every delegation.

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

Two baselines exist, on different models — kept separate rather than merged, since a mistake tied
to Gemini's behavior may not reproduce on Claude and vice versa.

**`claude-opus-4-6-thinking`, observed 2026-09-05** (`tests/unit/test_logging.py` task): clean on
the first pass — all four gate commands green, no `unittest.mock`, no attribution mark, report
matched `git diff` exactly. One real judgment call worth noting, not a mistake: it imported the
module's private `_correlation_id` `ContextVar` into the test to reset it between cases via an
autouse fixture, rather than isolating each test in its own thread — reasonable for a
`tests/unit/` module, flagged in its own report as a knowingly-coupled choice rather than hidden.
No rows to fix here yet; this table gets rebuilt again, not appended to, the next time a baseline
surfaces a real Opus 4.6 defect — don't add speculative rows.

**`gemini-3.1-pro-high`, observed 2026-09-05** (`app/core/db.py` task — retained for reference; not
reproduced on the current model):

| Failure | Fix |
| --- | --- |
| 9 `mypy --strict` failures: test functions missing `-> None` | Prompt requires the real `mypy --strict` pass, not just green `pytest` |
| `DbRole.APP == "app"` — mypy flags comparing a `StrEnum` to a raw string | Compare via `.value`; never compare a `StrEnum` member to a literal directly |
| Used `unittest.mock.Mock` | Forbidden — real fakes behind `Protocol`s only (S0 §11) |
| A test calling a `Protocol`'s `...` body just to pad coverage, asserting nothing real | Report must justify each test by the behavior it verifies |
| No docstrings; unsorted imports (`ruff I001`); only unit tests, never `lint-imports` | Full four-command gate, verbatim, is a required report field |
