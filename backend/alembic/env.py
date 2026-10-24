from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from orgpulse.config import get_settings
from orgpulse.models import Base

config = context.config
# Only when run as the `alembic` command: when Org+ migrates an organisation itself
# (orgpulse.orgs, passing "url"), logging is already set up, and fileConfig would
# silence every existing logger (the worker's included).
if config.config_file_name is not None and "url" not in config.attributes:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# An org database is migrated by passing its URL (orgpulse.orgs); otherwise DATABASE_URL.
target_url = config.attributes.get("url") or get_settings().sqlalchemy_url
config.set_main_option("sqlalchemy.url", target_url.replace("%", "%%"))
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
