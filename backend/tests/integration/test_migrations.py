"""Migration and schema-constraint tests against a DISPOSABLE PostgreSQL database.

Set TEST_DATABASE_URL to a database whose name ends in ``_test``. The tests run
``alembic downgrade``/``upgrade`` on it, so they refuse any other database and are
skipped when the variable is unset. Never point this at the real application database.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg import errors

TEST_URL = os.environ.get("TEST_DATABASE_URL")
BACKEND_DIR = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")

EXPECTED_PUBLIC = {
    "teams", "team_memberships", "projects", "project_memberships", "artifacts",
    "project_sources", "target_authorizations", "analysis_snapshots", "test_plans",
    "planned_tests", "approvals", "test_runs", "test_batches", "test_results",
    "job_events", "findings", "finding_events", "finding_evidence",
    "verification_attempts", "regression_tests", "llm_usage", "policies",
    "audit_events", "state_transitions", "test_batch_items", "test_case_results",
    "finding_groups",
}  # fmt: skip
EXPECTED_APP_USER = {"roles", "users", "sessions", "password_reset_tokens"}


def _dsn() -> str:
    assert TEST_URL
    return TEST_URL.replace("postgresql+psycopg://", "postgresql://")


def _alembic(action: str, revision: str) -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    os.environ["DATABASE_URL"] = _dsn()
    getattr(command, action)(cfg, revision)


def _tables(conn: psycopg.Connection, schema: str) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = %s AND table_type = 'BASE TABLE'",
        (schema,),
    ).fetchall()
    return {r[0] for r in rows}


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    with psycopg.connect(_dsn(), autocommit=True) as c:
        dbname = c.execute("SELECT current_database()").fetchone()
        assert dbname and dbname[0].endswith("_test"), "refusing to run on a non-test database"
        yield c


def test_upgrade_downgrade_roundtrip_preserves_existing_data(conn: psycopg.Connection) -> None:
    _alembic("downgrade", "base")
    conn.execute("DROP TABLE IF EXISTS public.legacy_probe")
    conn.execute("CREATE TABLE public.legacy_probe (id int PRIMARY KEY, note text)")
    conn.execute("INSERT INTO public.legacy_probe VALUES (1, 'keep me'), (2, 'and me')")

    _alembic("upgrade", "head")
    assert EXPECTED_PUBLIC <= _tables(conn, "public")
    assert _tables(conn, "app_user") == EXPECTED_APP_USER
    assert conn.execute("SELECT count(*) FROM public.legacy_probe").fetchone() == (2,)
    roles = {r[0] for r in conn.execute("SELECT name FROM app_user.roles").fetchall()}
    assert roles == {"developer", "admin", "super_admin"}

    _alembic("downgrade", "base")
    assert not (EXPECTED_PUBLIC & _tables(conn, "public"))
    assert (
        conn.execute(
            "SELECT 1 FROM information_schema.schemata WHERE schema_name = 'app_user'"
        ).fetchone()
        is None
    )
    assert conn.execute("SELECT count(*) FROM public.legacy_probe").fetchone() == (2,)

    _alembic("upgrade", "head")  # re-applicable after rollback
    assert conn.execute("SELECT count(*) FROM public.legacy_probe").fetchone() == (2,)
    conn.execute("DROP TABLE public.legacy_probe")


def test_downgrade_keeps_foreign_objects_in_app_user(conn: psycopg.Connection) -> None:
    _alembic("upgrade", "head")
    conn.execute("CREATE TABLE app_user.foreign_probe (id int)")
    _alembic("downgrade", "base")
    assert _tables(conn, "app_user") == {"foreign_probe"}
    conn.execute("DROP SCHEMA app_user CASCADE")  # test cleanup only; disposable DB
    _alembic("upgrade", "head")


class _Seed:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.user = conn.execute(
            "INSERT INTO app_user.users (email, display_name, password_hash) "
            "VALUES (%s, 'T', 'x') RETURNING id",
            (f"t{os.urandom(4).hex()}@example.test",),
        ).fetchone()[0]  # type: ignore[index]
        self.other = conn.execute(
            "INSERT INTO app_user.users (email, display_name, password_hash) "
            "VALUES (%s, 'O', 'x') RETURNING id",
            (f"o{os.urandom(4).hex()}@example.test",),
        ).fetchone()[0]  # type: ignore[index]
        self.project = conn.execute(
            "INSERT INTO public.projects (name, owner_user_id, application_type) "
            "VALUES (%s, %s, 'rest_api') RETURNING id",
            (f"p{os.urandom(4).hex()}", self.user),
        ).fetchone()[0]  # type: ignore[index]


@pytest.fixture
def seed(conn: psycopg.Connection) -> Iterator[_Seed]:
    _alembic("upgrade", "head")
    conn.autocommit = False
    try:
        yield _Seed(conn)
    finally:
        conn.rollback()
        conn.autocommit = True


def _expect(conn: psycopg.Connection, exc: type[Exception], sql: str, args: tuple = ()) -> None:
    conn.execute("SAVEPOINT s")
    with pytest.raises(exc):
        conn.execute(sql, args)
    conn.execute("ROLLBACK TO SAVEPOINT s")


def _plan_and_run(conn: psycopg.Connection, s: _Seed) -> tuple[object, object]:
    plan = conn.execute(
        "INSERT INTO public.test_plans (project_id, version, plan_mode, created_by) "
        "VALUES (%s, 1, 'automatic', %s) RETURNING id",
        (s.project, s.user),
    ).fetchone()[0]  # type: ignore[index]
    # Runs need an approved (hash-bound) plan: migration 0003.
    conn.execute(
        "UPDATE public.test_plans SET status = 'approved', content_sha256 = repeat('a', 64), "
        "policy_snapshot = '{}'::jsonb, submitted_by = %s, submitted_at = now() WHERE id = %s",
        (s.user, plan),
    )
    run = conn.execute(
        "INSERT INTO public.test_runs (project_id, plan_id, requested_by) "
        "VALUES (%s, %s, %s) RETURNING id",
        (s.project, plan, s.user),
    ).fetchone()[0]  # type: ignore[index]
    return plan, run


def test_run_state_transitions_are_enforced(conn: psycopg.Connection, seed: _Seed) -> None:
    _, run = _plan_and_run(conn, seed)
    _expect(
        conn,
        errors.CheckViolation,
        "UPDATE public.test_runs SET status='completed' WHERE id=%s",
        (run,),
    )
    conn.execute("UPDATE public.test_runs SET status='dispatched' WHERE id=%s", (run,))
    conn.execute("UPDATE public.test_runs SET status='running' WHERE id=%s", (run,))
    conn.execute("UPDATE public.test_runs SET status='cancel_requested' WHERE id=%s", (run,))
    conn.execute(
        "UPDATE public.test_runs SET status='cancelled', finished_at=now() WHERE id=%s", (run,)
    )
    # terminal state: no way out, and runs are never retried in place
    _expect(
        conn,
        errors.CheckViolation,
        "UPDATE public.test_runs SET status='queued' WHERE id=%s",
        (run,),
    )


def test_batch_retry_allowed_but_bounded(conn: psycopg.Connection, seed: _Seed) -> None:
    _, run = _plan_and_run(conn, seed)
    batch = conn.execute(
        "INSERT INTO public.test_batches (run_id, ordinal, max_attempts) VALUES (%s, 1, 2) RETURNING id",
        (run,),
    ).fetchone()[0]  # type: ignore[index]
    for status in ("dispatched", "running"):
        conn.execute("UPDATE public.test_batches SET status=%s WHERE id=%s", (status, batch))
    conn.execute(
        "UPDATE public.test_batches SET status='failed', finished_at=now() WHERE id=%s", (batch,)
    )
    conn.execute("UPDATE public.test_batches SET status='queued', attempt=2 WHERE id=%s", (batch,))
    _expect(
        conn,
        errors.CheckViolation,
        "UPDATE public.test_batches SET attempt=3 WHERE id=%s",
        (batch,),
    )


def test_confirmed_finding_requires_evidence(conn: psycopg.Connection, seed: _Seed) -> None:
    sql = (
        "INSERT INTO public.findings (project_id, fingerprint, title, category, detected_by, "
        "severity, verification_state) VALUES (%s, %s, 't', 'sqli', 'tool', 'high', 'confirmed') "
        "RETURNING id"
    )
    conn.execute("SAVEPOINT s")
    conn.execute(sql, (seed.project, "fp-no-evidence-1"))
    with pytest.raises(errors.CheckViolation):
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
    conn.execute("ROLLBACK TO SAVEPOINT s")

    fid = conn.execute(sql, (seed.project, "fp-with-evidence-1")).fetchone()[0]  # type: ignore[index]
    art = conn.execute(
        "INSERT INTO public.artifacts (project_id, kind, storage_key, sha256, size_bytes, content_type) "
        "VALUES (%s, 'log', %s, %s, 1, 'text/plain') RETURNING id",
        (seed.project, f"k/{os.urandom(4).hex()}", "a" * 64),
    ).fetchone()[0]  # type: ignore[index]
    conn.execute(
        "INSERT INTO public.finding_evidence (finding_id, artifact_id) VALUES (%s, %s)", (fid, art)
    )
    conn.execute("SET CONSTRAINTS ALL IMMEDIATE")  # passes: evidence present
    conn.execute("SET CONSTRAINTS ALL DEFERRED")
    conn.execute("DELETE FROM public.finding_evidence WHERE finding_id=%s", (fid,))
    with pytest.raises(errors.CheckViolation):
        conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_audit_log_is_append_only(conn: psycopg.Connection, seed: _Seed) -> None:
    aid = conn.execute(
        "INSERT INTO public.audit_events (actor_type, actor_user_id, action, outcome) "
        "VALUES ('user', %s, 'test.action', 'success') RETURNING id",
        (seed.user,),
    ).fetchone()[0]  # type: ignore[index]
    _expect(
        conn, errors.CheckViolation, "UPDATE public.audit_events SET action='x' WHERE id=%s", (aid,)
    )
    _expect(conn, errors.CheckViolation, "DELETE FROM public.audit_events WHERE id=%s", (aid,))


def test_source_and_authorization_guards(conn: psycopg.Connection, seed: _Seed) -> None:
    ins = (
        "INSERT INTO public.project_sources (project_id, source_type, name, git_url, target_url, "
        "environment, created_by) VALUES (%s, %s, 's', %s, %s, %s, %s)"
    )
    p, u = seed.project, seed.user
    conn.execute(ins, (p, "git_repository", "https://example.test/r.git", None, None, u))
    conn.execute(ins, (p, "localhost_url", None, "http://localhost:3000/", "local", u))
    conn.execute(ins, (p, "remote_url", None, "https://staging.example.test/", "staging", u))
    _expect(
        conn,
        errors.CheckViolation,
        ins,
        (p, "git_repository", "https://user:tok@example.test/r.git", None, None, u),
    )
    _expect(
        conn,
        errors.CheckViolation,
        ins,
        (p, "localhost_url", None, "http://evil.example.test/", "local", u),
    )
    _expect(
        conn,
        errors.CheckViolation,
        ins,
        (p, "remote_url", None, "https://x.example.test/", "local", u),
    )

    src = conn.execute(
        "SELECT id FROM public.project_sources WHERE source_type='remote_url'"
    ).fetchone()[0]  # type: ignore[index]
    auth = (
        "INSERT INTO public.target_authorizations (project_id, source_id, environment, scope, status, "
        "requested_by, decided_by, decided_at, decision_note, valid_from, valid_until) "
        "VALUES (%s, %s, 'production', '{}', 'approved', %s, %s, now(), %s, now(), now() + interval '1 day')"
    )
    # same person cannot approve their own production request; justification required
    _expect(conn, errors.CheckViolation, auth, (p, src, u, u, "long enough justification"))
    _expect(conn, errors.CheckViolation, auth, (p, src, u, seed.other, "short"))
    conn.execute(auth, (p, src, u, seed.other, "long enough justification"))


def test_high_risk_planned_test_must_require_approval(
    conn: psycopg.Connection, seed: _Seed
) -> None:
    plan = conn.execute(  # a draft: tests cannot be added to an approved plan (migration 0003)
        "INSERT INTO public.test_plans (project_id, version, plan_mode, created_by) "
        "VALUES (%s, 1, 'automatic', %s) RETURNING id",
        (seed.project, seed.user),
    ).fetchone()[0]  # type: ignore[index]
    ins = (
        "INSERT INTO public.planned_tests (plan_id, ordinal, name, category, tool, origin, "
        "risk_level, requires_approval) VALUES (%s, %s, 'n', 'security', 'zap', 'recommended', %s, %s)"
    )
    _expect(conn, errors.CheckViolation, ins, (plan, 1, "high", False))
    conn.execute(ins, (plan, 1, "high", True))
    conn.execute(ins, (plan, 2, "low", False))


def test_readiness_probes_against_disposable_database(conn: psycopg.Connection) -> None:
    from sentinel_ai.core.config import DatabaseSettings, load_settings
    from sentinel_ai.core.health import check_database, check_migrations
    from sentinel_ai.db.engine import create_db_engine

    _alembic("upgrade", "head")
    os.environ["DATABASE_URL"] = _dsn()
    engine = create_db_engine(load_settings(DatabaseSettings, _env_file=None))
    try:
        assert check_database(engine) == "ok"
        assert check_migrations(engine) == "ok"
        _alembic("downgrade", "0001_app_user_schema")
        assert check_migrations(engine) == "pending"
        _alembic("downgrade", "base")
        assert check_migrations(engine) == "pending"
    finally:
        engine.dispose()
        _alembic("upgrade", "head")


def test_ready_endpoint_end_to_end_on_disposable_database(conn: psycopg.Connection) -> None:
    from fastapi.testclient import TestClient

    from sentinel_ai.core.config import Settings
    from sentinel_ai.main import create_app

    _alembic("upgrade", "head")
    settings = Settings(_env_file=None, database_url=_dsn())  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as client:
        body = client.get("/api/v1/health/ready").json()
        assert body["status"] == "ready"
        assert body["checks"]["database"] == "ok" and body["checks"]["migrations"] == "ok"
        assert _dsn().split("@")[0].split("//")[1] not in str(body)


def _result_with_case(conn: psycopg.Connection, s: _Seed) -> tuple[object, object]:
    plan = conn.execute(
        "INSERT INTO public.test_plans (project_id, version, plan_mode, created_by) "
        "VALUES (%s, 1, 'automatic', %s) RETURNING id",
        (s.project, s.user),
    ).fetchone()[0]  # type: ignore[index]
    test = conn.execute(  # while the plan is still a draft (approved plans are frozen)
        "INSERT INTO public.planned_tests (plan_id, ordinal, name, category, tool, origin, "
        "risk_level, definition) VALUES (%s, 1, 't', 'functional', 'pytest', 'recommended', "
        "'low', '{}'::jsonb) RETURNING id",
        (plan,),
    ).fetchone()[0]  # type: ignore[index]
    conn.execute(
        "UPDATE public.test_plans SET status = 'approved', content_sha256 = repeat('a', 64), "
        "policy_snapshot = '{}'::jsonb, submitted_by = %s, submitted_at = now() WHERE id = %s",
        (s.user, plan),
    )
    run = conn.execute(
        "INSERT INTO public.test_runs (project_id, plan_id, requested_by) VALUES (%s, %s, %s) RETURNING id",
        (s.project, plan, s.user),
    ).fetchone()[0]  # type: ignore[index]
    batch = conn.execute(
        "INSERT INTO public.test_batches (run_id, ordinal) VALUES (%s, 1) RETURNING id", (run,)
    ).fetchone()[0]  # type: ignore[index]
    result = conn.execute(
        "INSERT INTO public.test_results (run_id, batch_id, planned_test_id, status) "
        "VALUES (%s, %s, %s, 'not_run') RETURNING id",
        (run, batch, test),
    ).fetchone()[0]  # type: ignore[index]
    return run, result


def test_not_run_and_test_case_rules(conn: psycopg.Connection, seed: _Seed) -> None:
    """Migration 0006: ``not_run`` is a result state; cases are bounded and attached to a result."""
    run, result = _result_with_case(conn, seed)
    ok = (
        "INSERT INTO public.test_case_results (result_id, run_id, ordinal, name, status) "
        "VALUES (%s, %s, %s, %s, %s)"
    )
    conn.execute(ok, (result, run, 1, "test_a", "passed"))
    _expect(conn, errors.UniqueViolation, ok, (result, run, 1, "dup", "passed"))
    _expect(conn, errors.CheckViolation, ok, (result, run, 2, "x", "blocked"))  # not a case state
    _expect(conn, errors.CheckViolation, ok, (result, run, 0, "x", "passed"))
    _expect(conn, errors.CheckViolation, ok, (result, run, 3, "", "passed"))
    _expect(conn, errors.CheckViolation, ok, (result, run, 3, "n" * 501, "passed"))
    too_long = "INSERT INTO public.test_case_results (result_id, run_id, ordinal, name, status, detail) VALUES (%s, %s, 4, 'n', 'failed', %s)"
    _expect(conn, errors.CheckViolation, too_long, (result, run, "d" * 10001))
    _expect(
        conn, errors.CheckViolation,
        "UPDATE public.test_results SET status = 'unknown' WHERE id = %s", (result,),
    )  # fmt: skip
    conn.execute("DELETE FROM public.test_results WHERE id = %s", (result,))
    left = conn.execute(
        "SELECT count(*) FROM public.test_case_results WHERE run_id = %s", (run,)
    ).fetchone()
    assert left == (0,)  # cases go with their result


def test_downgrading_0006_keeps_results_and_maps_not_run(conn: psycopg.Connection) -> None:
    _alembic("upgrade", "head")
    conn.autocommit = False
    try:
        seed = _Seed(conn)
        _, result = _result_with_case(conn, seed)
        conn.commit()
    finally:
        conn.autocommit = True
    try:
        _alembic("downgrade", "0005_job_queue")
        assert conn.execute("SELECT status FROM public.test_results WHERE id = %s", (result,)).fetchone() == ("skipped",)  # fmt: skip
        assert "test_case_results" not in _tables(conn, "public")
        with pytest.raises(errors.CheckViolation):  # autocommit connection: no savepoint needed
            conn.execute(
                "UPDATE public.test_results SET status = 'not_run' WHERE id = %s", (result,)
            )
    finally:
        _alembic("upgrade", "head")
        conn.execute("TRUNCATE app_user.users, public.projects CASCADE")


def _finding(conn: psycopg.Connection, seed: _Seed, fp: str) -> object:
    return conn.execute(
        "INSERT INTO public.findings (project_id, fingerprint, title, category, detected_by, "
        "severity) VALUES (%s, %s, 't', 'static_analysis', 'bandit', 'high') RETURNING id",
        (seed.project, fp),
    ).fetchone()[0]  # type: ignore[index]


def test_finding_columns_and_event_types_from_0007(conn: psycopg.Connection, seed: _Seed) -> None:
    """Migration 0007: confidence is bounded, defaults are conservative, new event types exist."""
    fid = _finding(conn, seed, "fp-defaults-0007")
    row = conn.execute(
        "SELECT confidence, verification_state, status, occurrences, source_id FROM public.findings WHERE id = %s",
        (fid,),
    ).fetchone()
    assert row == ("low", "unverified", "new", 1, None)  # a finding starts unverified and new
    _expect(conn, errors.CheckViolation, "UPDATE public.findings SET confidence = 'certain' WHERE id = %s", (fid,))  # fmt: skip
    _expect(conn, errors.CheckViolation, "UPDATE public.findings SET line_number = 0 WHERE id = %s", (fid,))  # fmt: skip
    _expect(conn, errors.CheckViolation, "UPDATE public.findings SET occurrences = 0 WHERE id = %s", (fid,))  # fmt: skip
    _expect(conn, errors.CheckViolation, "UPDATE public.findings SET limitations = repeat('x', 2001) WHERE id = %s", (fid,))  # fmt: skip
    _expect(conn, errors.ForeignKeyViolation, "UPDATE public.findings SET source_id = gen_random_uuid() WHERE id = %s", (fid,))  # fmt: skip
    event = "INSERT INTO public.finding_events (finding_id, event_type) VALUES (%s, %s)"
    conn.execute(event, (fid, "verification_attempt"))
    conn.execute(event, (fid, "reopened"))
    _expect(conn, errors.CheckViolation, event, (fid, "deleted"))
    _expect(conn, errors.CheckViolation, "UPDATE public.finding_events SET to_value = 'x' WHERE finding_id = %s", (fid,))  # fmt: skip


def test_downgrading_0007_keeps_findings(conn: psycopg.Connection) -> None:
    _alembic("upgrade", "head")
    conn.autocommit = False
    try:
        seed = _Seed(conn)
        fid = _finding(conn, seed, "fp-downgrade-0007")
        conn.execute("INSERT INTO public.finding_events (finding_id, event_type) VALUES (%s, 'reopened')", (fid,))  # fmt: skip
        conn.commit()
    finally:
        conn.autocommit = True
    try:
        _alembic("downgrade", "0006_test_cases")
        assert conn.execute("SELECT count(*) FROM public.findings WHERE id = %s", (fid,)).fetchone() == (1,)  # fmt: skip
        cols = {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'findings'").fetchall()}  # fmt: skip
        assert not cols & {"confidence", "rule_id", "limitations", "occurrences", "source_id"}
        assert conn.execute("SELECT count(*) FROM public.finding_events WHERE event_type = 'reopened'").fetchone() == (0,)  # fmt: skip
    finally:
        _alembic("upgrade", "head")
        conn.execute("TRUNCATE app_user.users, public.projects CASCADE")
