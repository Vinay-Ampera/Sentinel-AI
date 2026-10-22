"""Alembic environment.

The database URL comes only from DATABASE_URL (process environment or the untracked
backend/.env), loaded by sentinel_ai.core.config; never from alembic.ini or source. Alembic's own version table lives in the public schema.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from sentinel_ai.core.config import ConfigError, DatabaseSettings, load_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM models yet; schema is defined by explicit migrations (Stage 2).
target_metadata = None


def _database_url() -> str:
    """DATABASE_URL via the same loader as the app: process environment first, then
    backend/.env (or SENTINEL_ENV_FILE). Never read from alembic.ini."""
    try:
        return load_settings(DatabaseSettings).sqlalchemy_url
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (useful for reviewing DDL)."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
