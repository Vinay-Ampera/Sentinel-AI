import uuid

from conftest import GOOD_PASSWORD, Env, Session, signed_in
from fastapi.testclient import TestClient

from sentinel_ai.core import security
from support import PEPPER

API = "/api/v1"


def test_login_me_logout_flow(env: Env) -> None:
    user = env.make_user()
    s = Session(env)
    r = s.login(user["email"], user["password"])
    assert r.status_code == 200
    body = r.json()
    assert body["user"] == {
        "id": user["id"], "email": user["email"], "display_name": "Developer", "role": "developer",
    }  # fmt: skip
    assert "password" not in r.text and "hash" not in r.text
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie

    me = s.request("GET", f"{API}/auth/me")
    assert me.status_code == 200 and me.json()["csrf_token"] == body["csrf_token"]

    assert s.request("POST", f"{API}/auth/logout").status_code == 204
    assert s.request("GET", f"{API}/auth/me").status_code == 401
    assert [row[0] for row in env.audit("auth.logout")] == ["success"]


def test_only_a_keyed_hash_of_the_token_is_stored(env: Env) -> None:
    user = env.make_user()
    s = signed_in(env, user)
    raw = s.client.cookies.get("sentinel_session")
    assert raw
    (stored,) = env.pg.execute("SELECT token_hash FROM app_user.sessions").fetchone()  # type: ignore[misc]
    assert bytes(stored) == security.session_token_hash(PEPPER, raw)
    assert raw.encode() not in bytes(stored)


def test_login_failures_are_uniform_and_audited(env: Env) -> None:
    user = env.make_user()
    inactive = env.make_user(is_active=False)
    s = Session(env)
    responses = [
        s.login(user["email"], "wrong-password-123"),
        s.login("nobody@example.com", "wrong-password-123"),
        s.login(inactive["email"], inactive["password"]),
    ]
    assert {r.status_code for r in responses} == {401}
    assert len({r.text.replace(r.json()["error"]["request_id"], "") for r in responses}) == 1
    reasons = sorted(row[2]["reason"] for row in env.audit("auth.login"))
    assert reasons == ["bad_password", "inactive", "unknown"]


def test_email_is_case_insensitive_but_password_is_not(env: Env) -> None:
    user = env.make_user()
    assert Session(env).login(user["email"].upper(), user["password"]).status_code == 200
    assert Session(env).login(user["email"], user["password"].upper()).status_code == 401


def test_lockout_after_repeated_failures_even_with_correct_password(env: Env) -> None:
    user = env.make_user()
    s = Session(env)
    for _ in range(3):  # login_max_failures=3 in test settings
        assert s.login(user["email"], "wrong-password-123").status_code == 401
    assert s.login(user["email"], user["password"]).status_code == 401  # locked
    assert env.audit("auth.lockout")
    # Lock expiry restores access and a success clears the counter.
    env.pg.execute("UPDATE app_user.users SET locked_until = now() - interval '1 second'")
    assert s.login(user["email"], user["password"]).status_code == 200
    (count,) = env.pg.execute("SELECT failed_login_count FROM app_user.users").fetchone()  # type: ignore[misc]
    assert count == 0


def test_per_ip_rate_limit(pg) -> None:  # type: ignore[no-untyped-def]
    env = Env(pg, login_ip_max_attempts_per_minute=3)
    with TestClient(env.app):
        s = Session(env)
        codes = [s.login("nobody@example.com", "wrong-password-123").status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]


def test_session_rotates_on_each_login(env: Env) -> None:
    user = env.make_user()
    a, b = signed_in(env, user), signed_in(env, user)
    assert a.client.cookies.get("sentinel_session") != b.client.cookies.get("sentinel_session")
    assert a.request("GET", f"{API}/auth/me").status_code == 200  # sessions are independent


def test_invalid_expired_revoked_sessions_are_rejected(env: Env) -> None:
    user = env.make_user()
    s = signed_in(env, user)
    assert s.request("GET", f"{API}/auth/me").status_code == 200

    s.client.cookies.set("sentinel_session", "forged-" + uuid.uuid4().hex)
    assert s.request("GET", f"{API}/auth/me").status_code == 401

    real = signed_in(env, user)
    env.pg.execute("UPDATE app_user.sessions SET idle_expires_at = now() - interval '1 second'")
    assert real.request("GET", f"{API}/auth/me").status_code == 401  # idle timeout

    real = signed_in(env, user)
    env.pg.execute(
        "UPDATE app_user.sessions SET absolute_expires_at = now() - interval '1 second', created_at = now() - interval '2 hour'"
    )
    assert real.request("GET", f"{API}/auth/me").status_code == 401  # absolute timeout

    real = signed_in(env, user)
    env.pg.execute("UPDATE app_user.sessions SET revoked_at = now() WHERE revoked_at IS NULL")
    assert real.request("GET", f"{API}/auth/me").status_code == 401  # revoked


def test_activity_extends_idle_expiry_but_not_past_absolute(env: Env) -> None:
    user = env.make_user()
    s = signed_in(env, user)
    env.pg.execute("UPDATE app_user.sessions SET idle_expires_at = now() + interval '1 minute'")
    assert s.request("GET", f"{API}/auth/me").status_code == 200
    row = env.pg.execute(
        "SELECT idle_expires_at > now() + interval '20 minutes', "
        "idle_expires_at <= absolute_expires_at FROM app_user.sessions"
    ).fetchone()
    assert row == (True, True)


def test_deactivated_user_session_stops_working(env: Env) -> None:
    user = env.make_user()
    s = signed_in(env, user)
    env.pg.execute(
        "UPDATE app_user.users SET is_active = false, deactivated_at = now() WHERE id = %s",
        (user["id"],),
    )
    assert s.request("GET", f"{API}/auth/me").status_code == 401


def test_csrf_required_on_state_changing_requests(env: Env) -> None:
    user = env.make_user()
    s = signed_in(env, user)
    pw = {"current": user["password"], "new": "another-long-passphrase-1"}
    missing = s.request("POST", f"{API}/auth/password", csrf=False, json=pw)
    assert (missing.status_code, missing.json()["error"]["code"]) == (403, "csrf_failed")
    wrong = s.request(
        "POST", f"{API}/auth/password", csrf=False, json=pw, headers={"X-CSRF-Token": "0" * 64}
    )
    assert wrong.status_code == 403
    cross = s.request(
        "POST", f"{API}/auth/password", json=pw, headers={"Origin": "https://evil.example"}
    )
    assert (cross.status_code, cross.json()["error"]["code"]) == (403, "csrf_failed")
    # Another session's CSRF token does not work for this session.
    other = signed_in(env, env.make_user())
    assert (
        s.request(
            "POST", f"{API}/auth/logout", csrf=False, headers={"X-CSRF-Token": other.csrf}
        ).status_code
        == 403
    )
    assert s.request("GET", f"{API}/auth/me").status_code == 200  # reads need no CSRF token
    assert s.request("POST", f"{API}/auth/password", json=pw).status_code == 200


def test_change_password_revokes_other_sessions_and_enforces_policy(env: Env) -> None:
    user = env.make_user()
    a, b = signed_in(env, user), signed_in(env, user)
    new = "another-long-passphrase-1"
    bad = a.request(
        "POST", f"{API}/auth/password", json={"current": "nope-nope-nope-1", "new": new}
    )
    assert (bad.status_code, bad.json()["error"]["code"]) == (400, "invalid_current_password")
    weak = a.request(
        "POST", f"{API}/auth/password", json={"current": user["password"], "new": "short"}
    )
    assert (weak.status_code, weak.json()["error"]["code"]) == (422, "weak_password")
    same = a.request(
        "POST", f"{API}/auth/password", json={"current": user["password"], "new": user["password"]}
    )
    assert same.status_code == 422

    ok = a.request("POST", f"{API}/auth/password", json={"current": user["password"], "new": new})
    assert ok.status_code == 200 and ok.json() == {"other_sessions_revoked": 1}
    assert a.request("GET", f"{API}/auth/me").status_code == 200
    assert b.request("GET", f"{API}/auth/me").status_code == 401
    assert Session(env).login(user["email"], user["password"]).status_code == 401
    assert Session(env).login(user["email"], new).status_code == 200
    assert [r[0] for r in env.audit("auth.password_change")].count("success") == 1


def test_list_and_revoke_own_sessions_only(env: Env) -> None:
    alice, bob = env.make_user(), env.make_user()
    a1, a2, b1 = signed_in(env, alice), signed_in(env, alice), signed_in(env, bob)
    items = a1.request("GET", f"{API}/auth/sessions").json()["items"]
    assert len(items) == 2 and sum(i["current"] for i in items) == 1
    assert "token" not in a1.request("GET", f"{API}/auth/sessions").text
    bob_session = b1.request("GET", f"{API}/auth/sessions").json()["items"][0]["id"]
    # Alice cannot revoke Bob's session (looks nonexistent) ...
    assert a1.request("DELETE", f"{API}/auth/sessions/{bob_session}").status_code == 404
    assert b1.request("GET", f"{API}/auth/me").status_code == 200
    # ... but can revoke her own other session.
    other = next(i["id"] for i in items if not i["current"])
    assert a1.request("DELETE", f"{API}/auth/sessions/{other}").status_code == 204
    assert a2.request("GET", f"{API}/auth/me").status_code == 401


def test_secrets_never_reach_the_audit_log(env: Env) -> None:
    user = env.make_user()
    Session(env).login(user["email"], "super-secret-wrong-pw")
    signed_in(env, user)
    dump = str(env.pg.execute("SELECT detail, target_id FROM public.audit_events").fetchall())
    assert "super-secret-wrong-pw" not in dump and GOOD_PASSWORD not in dump


def test_swagger_style_same_origin_login_and_csrf_header(env: Env) -> None:
    """Swagger UI posts with Origin = the API's own origin and no frontend origin."""
    user = env.make_user()
    swagger = {"Origin": "http://testserver"}
    r = TestClient(env.app).post(
        f"{API}/auth/login",
        json={"email": user["email"], "password": user["password"]},
        headers=swagger,
    )
    assert r.status_code == 200
    # The cookie is kept by the client; the CSRF token is still mandatory for POST.
    c = TestClient(env.app, cookies=r.cookies)
    assert c.post(f"{API}/auth/logout", headers=swagger).status_code == 403
    csrf = {**swagger, "X-CSRF-Token": r.json()["csrf_token"]}
    assert c.post(f"{API}/auth/logout", headers=csrf).status_code == 204


def test_same_origin_login_is_refused_in_production(pg) -> None:  # type: ignore[no-untyped-def]
    prod = Env(pg, app_env="production", session_cookie_secure=True)
    user = prod.make_user()
    with TestClient(prod.app):
        c = TestClient(prod.app, raise_server_exceptions=False)
        body = {"email": user["email"], "password": user["password"]}
        refused = c.post(f"{API}/auth/login", json=body, headers={"Origin": "http://testserver"})
        assert (refused.status_code, refused.json()["error"]["code"]) == (403, "csrf_failed")
        allowed = c.post(
            f"{API}/auth/login", json=body, headers={"Origin": "http://localhost:5173"}
        )
        assert allowed.status_code == 200
