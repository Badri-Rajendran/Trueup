# Multi-stage build: `uv` resolves and installs into a venv in the builder stage; the runtime
# stage ships only that venv plus the application code, never the build toolchain (S0's own
# "no placeholder/debug code" bar extends to the image itself, not just the app).

FROM python:3.12-slim AS builder

# uv is installed from its own distroless image, not pip, so the builder never needs network
# access to PyPI's own resolver metadata beyond the lockfile's own package fetches.
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /bin/

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Dependencies first, from the lockfile alone, so an application-code change never invalidates
# this layer -- `--frozen` refuses to silently resolve a different set than uv.lock records.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# Then the application code, and the project itself (no dev dependency group in the image).
COPY app ./app
COPY wsgi.py alembic.ini ./
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runtime

# libpq is needed at runtime by psycopg[binary]'s C extension load path on slim images.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system trueup && useradd --system --gid trueup --create-home trueup

WORKDIR /app
COPY --from=builder --chown=trueup:trueup /app /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER trueup

EXPOSE 8000

# Migrations run as a separate CD step (never at container start -- a crash-looping web replica
# must never race a migration against itself). Gunicorn, not Flask's dev server, serves requests.
#
# gthread, not the default sync worker (S12 S6, NFR-18): a sync worker's arbiter heartbeat is
# only refreshed between requests, never while a response body is being written, so a long-lived
# SSE stream (GET /api/v1/events/stream, up to 30 minutes) would be SIGKILLed by murder_workers()
# at --timeout regardless of its value -- taking any other in-flight request on that worker with
# it. gthread's own run loop calls notify() independently of request threads, so it survives long
# streams; 2 workers x 32 threads gives 64 concurrent slots on 0.5 vCPU / 1Gi, each SSE connection
# pinning one thread blocked on Redis I/O (never CPU, never the DB pool -- the SSE view opens no
# UnitOfWork).
CMD ["gunicorn", "--bind", "0.0.0.0:8000", \
     "--worker-class", "gthread", "--workers", "2", "--threads", "32", \
     "--timeout", "60", "wsgi:app"]
