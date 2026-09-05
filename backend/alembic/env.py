"""Alembic environment.

Migrations run as `trueup_owner` — the schema owner — never as the web API's role. The web API's
credential must not be able to alter schema, in the same spirit as S0 §7.3's rule that it must not
be able to bypass RLS: capability is removed by credential, not by discipline.

The connection URL comes from settings, never from `alembic.ini`, so a database password never
sits in a committed file.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import get_settings

# Importing the package registers every entity on Base.metadata, which is what autogenerate
# diffs against. A model that is never imported is invisible to autogenerate.
from app.models import base as models_base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models_base.metadata

config.set_main_option("sqlalchemy.url", get_settings().sqlalchemy_url_owner)


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
