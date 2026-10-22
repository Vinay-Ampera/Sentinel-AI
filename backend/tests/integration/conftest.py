"""Fixtures for DB-backed auth tests. They TRUNCATE identity/project/audit tables, so they
refuse any database whose name does not end in ``_test``."""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from sentinel_ai.core import security
from sentinel_ai.main import create_app
from support import ORIGIN, make_settings

TEST_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parents[2]
GOOD_PASSWORD = "correct-horse-battery-9"


def dsn() -> str:
    assert TEST_URL
    return TEST_URL.replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture(scope="session")
def migrated_db() -> str:
    if not TEST_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    os.environ["DATABASE_URL"] = dsn()
    command.upgrade(cfg, "head")
    return dsn()


@pytest.fixture
def pg(migrated_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        row = conn.execute("SELECT current_database()").fetchone()
        assert row and row[0].endswith("_test"), "refusing to truncate a non-test database"
        conn.execute(
            "TRUNCATE app_user.users, public.teams, public.projects, public.audit_events CASCADE"
        )
        yield conn


class Env:
    def __init__(self, conn: psycopg.Connection, **settings: Any) -> None:
        self.pg = conn
        self.app = create_app(make_settings(dsn(), **settings))

    def make_user(
        self, role: str = "developer", password: str = GOOD_PASSWORD, **cols: Any
    ) -> dict:
        email = f"{role}-{uuid.uuid4().hex[:8]}@example.com"
        row = self.pg.execute(
            "INSERT INTO app_user.users (email, display_name, password_hash, role_name, is_active, deactivated_at) "
            "VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN NULL ELSE now() END) RETURNING id",
            (email, role.title(), security.hash_password(password), role,
             cols.get("is_active", True), cols.get("is_active", True)),
        ).fetchone()  # fmt: skip
        assert row
        return {"id": str(row[0]), "email": email, "password": password, "role": role}

    def audit(self, action: str) -> list[tuple]:
        return self.pg.execute(
            "SELECT outcome, actor_user_id, detail FROM public.audit_events WHERE action = %s "
            "ORDER BY id",
            (action,),
        ).fetchall()


class Session:
    """A signed-in (or anonymous) HTTP client with CSRF handling."""

    def __init__(self, env: Env) -> None:
        self.client = TestClient(env.app, raise_server_exceptions=True, headers={"Origin": ORIGIN})
        self.csrf: str | None = None

    def login(self, email: str, password: str) -> Any:
        r = self.client.post("/api/v1/auth/login", json={"email": email, "password": password})
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def request(self, method: str, url: str, csrf: bool = True, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}))
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        return self.client.request(method, url, headers=headers, **kwargs)


@pytest.fixture
def env(pg: psycopg.Connection) -> Iterator[Env]:
    e = Env(pg)
    with TestClient(e.app):  # runs the app lifespan once; Sessions share its state
        yield e


def signed_in(env: Env, user: dict) -> Session:
    s = Session(env)
    r = s.login(user["email"], user["password"])
    assert r.status_code == 200, r.text
    return s
