SHELL := /bin/bash
BACKEND := backend
UV := uv run --project $(BACKEND)

.DEFAULT_GOAL := help
.PHONY: help up down logs install env dev test test-unit test-integration test-api test-contract \
        lint format typecheck imports audit check migrate migrate-down migration worker job

help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --- Infrastructure -------------------------------------------------------------------------
# Postgres on 5433 and Redis on 6380, not the defaults, so Trueup cannot collide with another
# project's database on the same machine. Postgres, never SQLite, in every environment (S0 §11).

up: ## Start PostgreSQL and Redis
	docker compose up -d

down: ## Stop PostgreSQL and Redis (keeps the data volume)
	docker compose down

logs: ## Tail container logs
	docker compose logs -f

# --- Setup ----------------------------------------------------------------------------------

install: ## Install backend dependencies
	uv sync --project $(BACKEND)

env: ## Create .env from .env.example if it does not exist
	@test -f .env && echo ".env already exists, leaving it alone" \
		|| (cp .env.example .env && echo "Created .env - fill in SECRET_KEY and LOCAL_CIPHER_KEY")

# --- Development ----------------------------------------------------------------------------

dev: ## Run the API with reload
	$(UV) flask --app wsgi run --debug

worker: ## Run the outbox worker (always-on; drains job_outbox via LISTEN/NOTIFY)
	$(UV) flask --app wsgi jobs outbox-worker

job: ## Run one scheduled job locally, e.g. make job NAME=reconcile
	$(UV) flask --app wsgi jobs $(NAME)

# --- Tests ----------------------------------------------------------------------------------
# Four layers, one per concern (S0 §11). All of them need `make up` first.

test: ## Run the whole test suite
	$(UV) pytest

test-unit: ## Value objects, cash policy, TWR math - no database
	$(UV) pytest tests/unit

test-integration: ## Repositories, append-only guard, RLS policies, job idempotency
	$(UV) pytest tests/integration

test-api: ## Controllers via the Flask test client
	$(UV) pytest tests/api

test-contract: ## Each port's real adapter against its fake, same suite
	$(UV) pytest tests/contract

# --- Quality gates --------------------------------------------------------------------------

lint: ## Lint
	$(UV) ruff check app tests

format: ## Auto-format and fix what is safely fixable
	$(UV) ruff format app tests && $(UV) ruff check --fix app tests

typecheck: ## Strict type check
	$(UV) mypy --strict app

imports: ## Enforce the controllers -> services -> models -> core rule (S0 §3)
	$(UV) lint-imports

audit: ## Scan dependencies for known vulnerabilities
	$(UV) pip-audit

check: lint typecheck imports test ## Everything CI runs

# --- Migrations -----------------------------------------------------------------------------
# Run as trueup_owner. Every schema change ships its migration in the same change (S0 §12).

migrate: ## Apply migrations
	$(UV) alembic upgrade head

migrate-down: ## Roll back one revision
	$(UV) alembic downgrade -1

migration: ## Autogenerate a migration, e.g. make migration M="add ledger tables"
	$(UV) alembic revision --autogenerate -m "$(M)"
