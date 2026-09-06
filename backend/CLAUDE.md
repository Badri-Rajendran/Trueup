# Backend Instructions

Python + Flask service. Follow the repository rules in [../CLAUDE.md](../CLAUDE.md) as well.

## Architecture (MVC, extended — ADR 14)

MVC is preserved; three more layers hold what controller/view/model has no room for. Full design in
[`docs/specs/00-backend-foundation-design.md`](../docs/specs/00-backend-foundation-design.md).

| Layer | Path | Responsibility |
| --- | --- | --- |
| Core | `app/core/` | Value objects (`Money`/`Units`/`Price`), unit-of-work, base repository, errors, security decorators. Imports nothing else under `app/`. |
| Model | `app/models/` | SQLAlchemy entities and one repository per aggregate. No business rules. |
| Service | `app/services/` | Domain and application logic — one clear responsibility per class. |
| Integration | `app/integrations/` | Ports (`Protocol`s) + adapters. The only code that calls Alpaca/Plaid/Stripe. |
| Controller | `app/controllers/` | Flask blueprints; validate the request, call one service, return a view's output. |
| View | `app/views/` | Response serialization via explicit schemas only — never a raw entity. |
| Job | `app/jobs/` | One class per scheduled job, each with a CLI entrypoint (ADR 13). Imports no scheduler. |

- Dependency direction, enforced by `import-linter` in CI: `controllers → services → models → core`;
  `services → integrations` only through `Protocol`s, never a concrete adapter.
- Keep settings in `app/config.py`, extension instances in `app/extensions.py`, and the app
  entrypoint in `wsgi.py`.
- Keep every controller, view, model, service, and adapter responsible for exactly one thing.
- When a responsibility grows, split it into smaller units instead of extending it.
- Follow SOLID: focused interfaces (`Protocol`s in `integrations/ports.py`), constructor-injected
  dependencies, no layer reaching past its neighbour.
- Follow DRY: look for an existing model, service, repository, or fixture before writing a new one.
- Follow KISS: pick the simplest design that meets the requirement; no speculative abstraction.
- Use `Money`/`Units`/`Price` (`app/core/money.py`) for every money or unit value — never a bare
  `Decimal` — so mixing dimensions is a type error, not a review concern (ADR 16).
- Every repository read of a bitemporally-sensitive aggregate takes `as_of: Watermark` with no
  default (ADR 6, ADR 14).

## Commands

```sh
uv sync                                          # install dependencies
uv run flask --app wsgi run --debug              # dev server
uv run pytest                                    # run tests
uv run mypy --strict app                         # type check
uv run ruff check app tests                      # lint
uv run lint-imports                              # enforce the layer dependency rule
uv run alembic revision --autogenerate -m "..."  # create a migration
uv run alembic upgrade head                      # apply migrations
uv run flask jobs <name>                         # run a scheduled job locally (ADR 13)
```

## Tooling

- Run every command with `uv run` (e.g. `uv run pytest`); never invoke `python` or `pip` directly.
- Add dependencies with `uv add <pkg>`, dev tools with `uv add --dev <pkg>`; never hand-edit
  `pyproject.toml`.
- Use Pydantic for request/response validation and parsing, and `pydantic-settings` for configuration
  in `app/config.py`.
- Read all configuration through settings; never hard-code values or touch `os.environ` inline.
- Ship every schema change with an Alembic migration in the same change.


## Working style

- Build iteratively — implement and test one functionality at a time, never several at once.
- Keep commit messages and PR descriptions crisp, bulleted, and precise: what changed and why.
- Keep every response and document readable and short enough to scan; use bullets over prose.
