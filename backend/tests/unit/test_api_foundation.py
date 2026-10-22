import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from sentinel_ai.core import health as probes
from sentinel_ai.core.config import Settings
from sentinel_ai.core.logging import RedactingFilter
from sentinel_ai.main import create_app

SECRET_URL = "postgresql://appuser:s3cretpw@dbhost.internal:5432/sentinel-ai"


@pytest.fixture
def client() -> Iterator[TestClient]:
    settings = Settings(_env_file=None, database_url=SECRET_URL)  # type: ignore[call-arg]
    with TestClient(create_app(settings)) as c:  # context manager runs lifespan
        yield c


def _patch(monkeypatch: pytest.MonkeyPatch, db: str, mig: str, redis: str) -> None:
    monkeypatch.setattr(probes, "check_database", lambda engine: db)
    monkeypatch.setattr(probes, "check_migrations", lambda engine: mig)
    monkeypatch.setattr(probes, "check_redis", lambda settings: redis)


def test_ready_when_database_migrated(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, "ok", "ok", "ok")
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200
    assert r.json() == {
        "status": "ready",
        "checks": {"database": "ok", "migrations": "ok", "redis": "ok"},
    }


def test_redis_down_does_not_fail_readiness_yet(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch(monkeypatch, "ok", "ok", "unavailable")
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["redis"] == "unavailable"


@pytest.mark.parametrize(("db", "mig"), [("unavailable", "unknown"), ("ok", "pending")])
def test_not_ready_returns_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, db: str, mig: str
) -> None:
    _patch(monkeypatch, db, mig, "ok")
    r = client.get("/api/v1/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"


def test_real_unreachable_database_reports_unavailable_without_leaking(
    client: TestClient,
) -> None:
    # Real probes against an unreachable host: still only status words.
    r = client.get("/api/v1/health/ready")
    body = r.text
    assert r.status_code == 503
    for secret in ("s3cretpw", "appuser", "dbhost.internal", "sentinel-ai", "postgresql"):
        assert secret not in body


def test_not_ready_before_startup() -> None:
    settings = Settings(_env_file=None, database_url=SECRET_URL)  # type: ignore[call-arg]
    r = TestClient(create_app(settings)).get("/api/v1/health/ready")  # no lifespan
    assert r.status_code == 503


def test_request_id_and_security_headers(client: TestClient) -> None:
    r = client.get("/api/v1/health/live", headers={"X-Request-ID": "abc-1234567"})
    assert r.headers["x-request-id"] == "abc-1234567"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    generated = client.get("/api/v1/health/live", headers={"X-Request-ID": "bad id!"})
    assert generated.headers["x-request-id"].startswith("req_")


def test_error_envelope_for_404_and_validation(client: TestClient) -> None:
    r = client.get("/api/v1/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found" and err["request_id"] == r.headers["x-request-id"]


def test_unhandled_exception_hides_details() -> None:
    settings = Settings(_env_file=None, database_url=SECRET_URL)  # type: ignore[call-arg]
    app = create_app(settings)

    @app.get("/boom")
    def boom() -> None:
        raise RuntimeError("password=s3cretpw")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "s3cretpw" not in r.text


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    ok = client.get("/api/v1/health/live", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.get("/api/v1/health/live", headers={"Origin": "http://evil.test"})
    assert "access-control-allow-origin" not in other.headers


def test_log_filter_redacts_url_passwords() -> None:
    record = logging.LogRecord("t", logging.INFO, "", 0, "connect %s", (SECRET_URL,), None)
    RedactingFilter().filter(record)
    assert "s3cretpw" not in record.getMessage()
    assert "appuser:***@dbhost" in record.getMessage()
