"""Infrastructure probes for readiness. Results are fixed status words only: no URLs,
credentials, hostnames, or exception text ever leave this module."""

import logging
from pathlib import Path
from typing import Literal

import redis
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text

from sentinel_ai.core.config import BACKEND_DIR, Settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = BACKEND_DIR / "migrations"

DatabaseStatus = Literal["ok", "unavailable"]
MigrationStatus = Literal["ok", "pending", "unknown"]
RedisStatus = Literal["ok", "unavailable"]


def check_database(engine: Engine) -> DatabaseStatus:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 - report status only
        logger.warning("database check failed: %s", type(exc).__name__)
        return "unavailable"


def check_migrations(engine: Engine, migrations_dir: Path = MIGRATIONS_DIR) -> MigrationStatus:
    """'ok' when the database is at the newest migration, 'pending' when behind/empty."""
    try:
        cfg = Config()
        cfg.set_main_option("script_location", str(migrations_dir))
        head = ScriptDirectory.from_config(cfg).get_current_head()
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"version_table_schema": "public"})
            current = context.get_current_revision()
        return "ok" if current == head else "pending"
    except Exception as exc:  # noqa: BLE001
        logger.warning("migration check failed: %s", type(exc).__name__)
        return "unknown"


def check_redis(settings: Settings) -> RedisStatus:
    try:
        client = redis.Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=settings.redis_timeout_seconds,
            socket_timeout=settings.redis_timeout_seconds,
        )
        try:
            return "ok" if client.ping() else "unavailable"
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis check failed: %s", type(exc).__name__)
        return "unavailable"
