"""Every protected route rejects anonymous callers (no database needed: the session
cookie is missing, so no lookup happens)."""

import re
from collections.abc import Iterator

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from sentinel_ai.api.deps import check_origin
from sentinel_ai.core.config import Settings
from sentinel_ai.core.errors import DomainError
from sentinel_ai.main import create_app
from support import make_settings

PUBLIC = {("POST", "/api/v1/auth/login")}


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app(make_settings()), raise_server_exceptions=False) as c:
        yield c


def _protected_routes() -> list[tuple[str, str]]:
    paths = create_app(make_settings()).openapi()["paths"]
    found = [(m.upper(), p) for p, ops in paths.items() for m in ops]
    return [(m, p) for m, p in found if (m, p) not in PUBLIC and not p.startswith("/api/v1/health")]


def test_all_non_public_routes_require_a_session(client: TestClient) -> None:
    routes = _protected_routes()
    assert len(routes) >= 20
    zero = "00000000-0000-0000-0000-000000000000"
    for method, path in routes:
        url = re.sub(r"\{[^}]+\}", zero, path)
        r = client.request(method, url, json={})
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "unauthenticated"


def test_garbage_session_cookie_is_rejected_without_a_database_hit(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sentinel_ai.repositories import identity

    monkeypatch.setattr(identity, "find_active_session", lambda db, th: None)
    client.cookies.set("sentinel_session", "not-a-real-token")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_auth_not_configured_fails_closed() -> None:
    settings = make_settings(session_token_pepper=None)
    with TestClient(create_app(settings), raise_server_exceptions=False) as c:
        r = c.get("/api/v1/auth/me")
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "auth_not_configured"
        assert (
            c.post("/api/v1/auth/login", json={"email": "a@b.co", "password": "x"}).status_code
            == 503
        )


def test_login_validates_body_and_rejects_unknown_fields(client: TestClient) -> None:
    assert client.post("/api/v1/auth/login", json={"email": "a@b.co"}).status_code == 422
    r = client.post(
        "/api/v1/auth/login", json={"email": "a@b.co", "password": "x", "role": "admin"}
    )
    assert r.status_code == 422


def test_login_from_disallowed_origin_is_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/auth/login",
        json={"email": "a@b.co", "password": "x"},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


def _origin_request(origin: str | None, base: str = "http://localhost:8000") -> Request:
    headers = [(b"host", base.split("//")[1].encode())]
    if origin:
        headers.append((b"origin", origin.encode()))
    scheme = base.split(":")[0]
    scope = {
        "type": "http",
        "method": "POST",
        "scheme": scheme,
        "path": "/",
        "query_string": b"",
        "headers": headers,
        "server": ("localhost", 8000),
    }
    return Request(scope)


def _denied(request: Request, settings: Settings) -> bool:
    try:
        check_origin(request, settings)
    except DomainError as exc:
        return exc.status_code == 403 and exc.code == "csrf_failed"
    return False


def test_swagger_same_origin_allowed_in_development_only() -> None:
    dev = make_settings()
    prod = make_settings(app_env="production", session_cookie_secure=True)
    swagger = _origin_request("http://localhost:8000")
    assert not _denied(swagger, dev)
    assert _denied(swagger, prod)  # production: allow-list only


def test_frontend_allow_list_still_applies_everywhere() -> None:
    for settings in (
        make_settings(),
        make_settings(app_env="production", session_cookie_secure=True),
    ):
        assert not _denied(_origin_request("http://localhost:5173"), settings)
        assert not _denied(_origin_request(None), settings)  # non-browser client, no Origin


def test_cross_site_origins_are_rejected_in_every_environment() -> None:
    prod = make_settings(app_env="production", session_cookie_secure=True)
    for settings in (make_settings(), prod):
        for origin in (
            "https://evil.example",
            "http://localhost:9999",  # same host, different port
            "https://localhost:8000",  # same host, different scheme
            "http://localhost:8000.evil.example",
            "null",
        ):
            assert _denied(_origin_request(origin), settings), origin


def test_openapi_declares_csrf_header_scheme() -> None:
    schemes = create_app(make_settings()).openapi()["components"]["securitySchemes"]
    assert any(v.get("name") == "X-CSRF-Token" and v["in"] == "header" for v in schemes.values())
