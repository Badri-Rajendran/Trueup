# Changelog

## Unreleased

- Restructure `CLAUDE.md` into grouped sections (Stack, Ways of working, Pull requests, CI/CD,
  Security, Testing, Documentation); declare the app production-grade, pin the stack (Flask,
  PostgreSQL, Alembic, React, Docker, GitHub Actions, Azure), and add rules for per-feature PRs via
  the GitHub plugin, comprehensive CI/CD, OWASP/AI security, API throttling tests, and UI component
  tests.
- Replace the broken self-referencing `backend/CLAUDE.md` stub with backend engineering standards:
  MVC layering (controllers/views/models), `uv` tooling, Pydantic, Pytest-per-functionality, and
  DRY/SOLID/KISS/single-responsibility rules.
- Rewrite `frontend/CLAUDE.md` as concise feature-based React standards: domain folders under
  `src/features/`, standard global directories, `useEffect`/memoization/state-grouping discipline,
  composition over props drilling, layered architecture, and SOLID/DRY/KISS.
- Fix a source-of-truth conflict: `docs/architecture.md` mapped the backend MVC layers (routes,
  serialization, logic) the opposite way from `backend/CLAUDE.md`; both now agree on
  controllers = routes, views = serializers, models = entities + business rules.
- Remove `CONTRIBUTING.md` (stale, contradicted `uv run pytest` with bare `pytest`); fold its one
  unique rule (never commit credentials or real customer/insurance data) into root `CLAUDE.md`.
- Add a Commands section and Alembic migration rule to `backend/CLAUDE.md`; add a Testing section,
  `npm test`, and a "target layout" note to `frontend/CLAUDE.md` — both standards were previously
  mandated in root `CLAUDE.md` with no corresponding command or section in the service files.
- Add the missing SQLAlchemy stack row, pin Vitest (was "Vitest/Jest"), remove a duplicate branch
  rule, and split an overloaded CI bullet in root `CLAUDE.md`.
- Add `docs/requirements/project-description.md` with the retail investing product brief, closing
  the dead `docs/requirements/` reference in root `CLAUDE.md`.
