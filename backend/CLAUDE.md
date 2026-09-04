# Backend Instructions

Python + Flask service. Follow the repository rules in [../CLAUDE.md](../CLAUDE.md) as well.

## Architecture (MVC)

| Layer | Path | Responsibility |
| --- | --- | --- |
| Controller | `app/controllers/` | Flask blueprints and routes; validate the request, call models, return a view's output. |
| View | `app/views/` | Response serialization and output shaping only. |
| Model | `app/models/` | SQLAlchemy entities, the rules that belong to one entity, and queries. |

- Keep settings in `app/config.py`, extension instances in `app/extensions.py`, and the app
  entrypoint in `wsgi.py`.
- Put rules spanning several entities in their own module under `app/models/`; never bloat one
  entity with them.
- Keep every controller, view, and model responsible for exactly one thing.
- When a responsibility grows, split the entity into smaller ones instead of extending it.
- Follow SOLID: focused interfaces, injected dependencies, no layer reaching past its neighbour.
- Follow DRY: look for an existing model, helper, or fixture before writing a new one.
- Follow KISS: pick the simplest design that meets the requirement; no speculative abstraction.

## Commands

```sh
uv sync                                          # install dependencies
uv run flask --app wsgi run --debug              # dev server
uv run pytest                                    # run tests
uv run alembic revision --autogenerate -m "..."  # create a migration
uv run alembic upgrade head                      # apply migrations
```

## Tooling

- Run every command with `uv run` (e.g. `uv run pytest`); never invoke `python` or `pip` directly.
- Add dependencies with `uv add <pkg>`, dev tools with `uv add --dev <pkg>`; never hand-edit
  `pyproject.toml`.
- Use Pydantic for request/response validation and parsing, and `pydantic-settings` for configuration
  in `app/config.py`.
- Read all configuration through settings; never hard-code values or touch `os.environ` inline.
- Ship every schema change with an Alembic migration in the same change.

## Testing

- Pytest is the only test framework; tests mirror the layers in `tests/test_controllers.py`,
  `test_views.py`, and `test_models.py`.
- Keep shared fixtures in `tests/conftest.py` and reuse them rather than repeating setup.
- After building each functionality, immediately write and run its pytest with `uv run pytest`.
- Cover happy path, validation errors, authorization, and error responses; a functionality is done
  only when its tests pass.

## Working style

- Build iteratively — implement and test one functionality at a time, never several at once.
- Keep commit messages and PR descriptions crisp, bulleted, and precise: what changed and why.
- Keep every response and document readable and short enough to scan; use bullets over prose.
