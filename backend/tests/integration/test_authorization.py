import uuid
from collections.abc import Iterator

import pytest
from conftest import Env, Session, signed_in
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from sentinel_ai.api.deps import require_permission, require_project_access
from sentinel_ai.core.permissions import AccessLevel, Permission
from sentinel_ai.services import users as user_service
from sentinel_ai.services.audit import RequestContext
from support import ORIGIN

API = "/api/v1"
NEW_PW = "brand-new-passphrase-7"


def new_user_body(role: str = "developer") -> dict[str, str]:
    return {
        "email": f"new-{uuid.uuid4().hex[:8]}@example.com",
        "display_name": "New Person",
        "role": role,
        "password": NEW_PW,
    }


# ---- role enforcement on user administration ---------------------------------------------


def test_developer_is_denied_admin_endpoints_and_denials_are_audited(env: Env) -> None:
    dev = env.make_user("developer")
    target = env.make_user("developer")
    s = signed_in(env, dev)
    assert s.request("GET", f"{API}/users").status_code == 403
    assert s.request("POST", f"{API}/admin/users", json=new_user_body()).status_code == 403
    r = s.request("PATCH", f"{API}/admin/users/{target['id']}", json={"is_active": False})
    assert (r.status_code, r.json()["error"]["code"]) == (403, "forbidden")
    denied = [row for row in env.audit("authz.denied") if row[0] == "denied"]
    assert len(denied) == 3 and all(str(row[1]) == dev["id"] for row in denied)
    (active,) = env.pg.execute(
        "SELECT is_active FROM app_user.users WHERE id = %s", (target["id"],)
    ).fetchone()  # type: ignore[misc]
    assert active is True


def test_admin_manages_developers_only(env: Env) -> None:
    admin, dev = env.make_user("admin"), env.make_user("developer")
    other_admin, sa = env.make_user("admin"), env.make_user("super_admin")
    s = signed_in(env, admin)

    assert s.request("GET", f"{API}/users").status_code == 200
    created = s.request("POST", f"{API}/admin/users", json=new_user_body("developer"))
    assert created.status_code == 201 and created.json()["role"] == "developer"
    assert "password" not in created.text

    for role in ("admin", "super_admin"):  # cannot mint privileged accounts
        assert s.request("POST", f"{API}/admin/users", json=new_user_body(role)).status_code == 403

    ok = s.request("PATCH", f"{API}/admin/users/{dev['id']}", json={"display_name": "Renamed"})
    assert ok.status_code == 200 and ok.json()["display_name"] == "Renamed"
    # cannot escalate a developer, nor touch other privileged accounts
    assert (
        s.request("PATCH", f"{API}/admin/users/{dev['id']}", json={"role": "admin"}).status_code
        == 403
    )
    for victim in (other_admin, sa):
        r = s.request("PATCH", f"{API}/admin/users/{victim['id']}", json={"is_active": False})
        assert r.status_code == 403
    assert {row[0] for row in env.audit("user.update")} == {"success", "denied"}


def test_admin_cannot_change_own_role_or_deactivate_self(env: Env) -> None:
    admin = env.make_user("admin")
    s = signed_in(env, admin)
    assert (
        s.request(
            "PATCH", f"{API}/admin/users/{admin['id']}", json={"role": "super_admin"}
        ).status_code
        == 403
    )
    assert (
        s.request(
            "PATCH", f"{API}/admin/users/{admin['id']}", json={"is_active": False}
        ).status_code
        == 403
    )


def test_super_admin_role_changes_and_session_revocation(env: Env) -> None:
    sa, dev = env.make_user("super_admin"), env.make_user("developer")
    root, victim = signed_in(env, sa), signed_in(env, dev)
    r = root.request("PATCH", f"{API}/admin/users/{dev['id']}", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    assert victim.request("GET", f"{API}/auth/me").status_code == 401  # sessions revoked
    # fresh login picks up the new role (privileges are read server-side, never cached in a cookie)
    assert signed_in(env, dev).request("GET", f"{API}/users").status_code == 200

    assert (
        root.request(
            "PATCH", f"{API}/admin/users/{dev['id']}", json={"is_active": False}
        ).status_code
        == 200
    )
    assert Session(env).login(dev["email"], dev["password"]).status_code == 401
    assert (
        root.request(
            "PATCH", f"{API}/admin/users/{uuid.uuid4()}", json={"is_active": False}
        ).status_code
        == 404
    )
    assert (
        root.request("PATCH", f"{API}/admin/users/{dev['id']}", json={"role": "root"}).status_code
        == 422
    )


def test_super_admin_cannot_act_on_themselves_over_http(env: Env) -> None:
    first, second = env.make_user("super_admin"), env.make_user("super_admin")
    s = signed_in(env, first)
    for change in ({"is_active": False}, {"role": "developer"}):
        assert (
            s.request("PATCH", f"{API}/admin/users/{first['id']}", json=change).status_code == 403
        )
    # Removing the *other* Super Admin is fine while this one stays active.
    assert (
        s.request("PATCH", f"{API}/admin/users/{second['id']}", json={"role": "admin"}).status_code
        == 200
    )


def test_last_active_super_admin_is_protected_by_the_service(env: Env) -> None:
    """Defence in depth: if the acting Super Admin was removed concurrently, the remaining
    one cannot be demoted or deactivated through the service either."""
    from sentinel_ai.core.errors import DomainError
    from sentinel_ai.db.engine import create_session_factory
    from sentinel_ai.repositories import identity

    actor, last = env.make_user("super_admin"), env.make_user("super_admin")
    env.pg.execute(
        "UPDATE app_user.users SET is_active = false, deactivated_at = now() WHERE id = %s",
        (actor["id"],),
    )
    ctx = RequestContext("t", None, None)
    with create_session_factory(env.app.state.engine)() as db:
        acting = identity.get_user(db, uuid.UUID(actor["id"]))
        assert acting is not None
        for change in ({"is_active": False}, {"role": "developer"}):
            with pytest.raises(DomainError) as err:
                user_service.update_user(db, ctx, acting, uuid.UUID(last["id"]), **change)
            assert (err.value.status_code, err.value.code) == (409, "last_super_admin")
        db.rollback()
    (count,) = env.pg.execute(
        "SELECT count(*) FROM app_user.users WHERE role_name = 'super_admin' AND is_active"
    ).fetchone()  # type: ignore[misc]
    assert count == 1


def test_create_user_validation_and_conflicts(env: Env) -> None:
    sa = env.make_user("super_admin")
    s = signed_in(env, sa)
    body = new_user_body("admin")
    assert s.request("POST", f"{API}/admin/users", json=body).status_code == 201
    assert s.request("POST", f"{API}/admin/users", json=body).status_code == 409
    weak = {**new_user_body(), "password": "short"}
    assert (
        s.request("POST", f"{API}/admin/users", json=weak).json()["error"]["code"]
        == "weak_password"
    )
    assert (
        s.request(
            "POST", f"{API}/admin/users", json={**new_user_body(), "email": "nope"}
        ).status_code
        == 422
    )
    assert (
        s.request(
            "POST", f"{API}/admin/users", json={**new_user_body(), "is_admin": True}
        ).status_code
        == 422
    )
    created = Session(env).login(body["email"], NEW_PW)
    assert created.status_code == 200 and created.json()["user"]["role"] == "admin"
    assert any(row[0] == "success" for row in env.audit("user.create"))


def test_user_list_never_exposes_credentials(env: Env) -> None:
    sa = env.make_user("super_admin")
    env.make_user("developer")
    items = signed_in(env, sa).request("GET", f"{API}/users", params={"q": "devel"}).json()["items"]
    assert items and all(
        set(i)
        == {"id", "email", "display_name", "role", "is_active", "last_login_at", "created_at"}
        for i in items
    )


# ---- project-scoped authorization -----------------------------------------------------------


@pytest.fixture
def project_env(pg) -> Iterator[Env]:  # type: ignore[no-untyped-def]
    """The real app plus a throwaway router that exercises the project-access guard
    (project routes themselves arrive in Stage 5)."""
    e = Env(pg)
    router = APIRouter()
    for level in AccessLevel:
        router.add_api_route(
            f"/probe/{level.name.lower()}/{{project_id}}",
            lambda project_id: {"ok": True},
            dependencies=[
                Depends(require_permission(Permission.PROJECT_VIEW)),
                Depends(require_project_access(level)),
            ],
        )
    e.app.include_router(router, prefix="/api/v1")
    with TestClient(e.app):
        yield e


def _project(env: Env, owner: dict, **cols: object) -> str:
    row = env.pg.execute(
        "INSERT INTO public.projects (name, owner_user_id, application_type, team_id, team_access) "
        "VALUES (%s, %s, 'web_app', %s, %s) RETURNING id",
        (
            f"p-{uuid.uuid4().hex[:6]}",
            owner["id"],
            cols.get("team_id"),
            cols.get("team_access", "none"),
        ),
    ).fetchone()
    assert row
    return str(row[0])


def _probe(s: Session, level: str, project_id: str) -> int:
    return s.request("GET", f"{API}/probe/{level}/{project_id}").status_code


def test_cross_project_access_is_denied_with_404(project_env: Env) -> None:
    env = project_env
    alice, bob = env.make_user("developer"), env.make_user("developer")
    p_alice, p_bob = _project(env, alice), _project(env, bob)
    a = signed_in(env, alice)
    assert _probe(a, "manage", p_alice) == 200
    assert _probe(a, "read", p_bob) == 404  # someone else's project: indistinguishable from missing
    assert _probe(a, "read", str(uuid.uuid4())) == 404


def test_membership_levels_are_hierarchical(project_env: Env) -> None:
    env = project_env
    owner, member = env.make_user("developer"), env.make_user("developer")
    project = _project(env, owner)
    env.pg.execute(
        "INSERT INTO public.project_memberships (project_id, user_id, access_level) VALUES (%s, %s, 'run')",
        (project, member["id"]),
    )
    m = signed_in(env, member)
    assert [_probe(m, lv, project) for lv in ("read", "run", "manage")] == [200, 200, 403]


def test_team_access_and_team_ownership(project_env: Env) -> None:
    env = project_env
    owner, mate, lead, outsider = (env.make_user("developer") for _ in range(4))
    team = str(
        env.pg.execute(
            "INSERT INTO public.teams (name, created_by) VALUES (%s, %s) RETURNING id",
            (f"t-{uuid.uuid4().hex[:6]}", owner["id"]),
        ).fetchone()[0]
    )  # type: ignore[index]
    for user, role in ((mate, "member"), (lead, "owner")):
        env.pg.execute(
            "INSERT INTO public.team_memberships (team_id, user_id, team_role) VALUES (%s, %s, %s)",
            (team, user["id"], role),
        )
    shared = _project(env, owner, team_id=team, team_access="read")
    private = _project(env, owner, team_id=team, team_access="none")
    mate_s, lead_s, out_s = signed_in(env, mate), signed_in(env, lead), signed_in(env, outsider)
    assert [_probe(mate_s, lv, shared) for lv in ("read", "run")] == [200, 403]
    assert _probe(mate_s, "read", private) == 404
    assert _probe(lead_s, "manage", private) == 200
    assert _probe(out_s, "read", shared) == 404


def test_admin_has_no_implicit_global_access_but_super_admin_does(project_env: Env) -> None:
    env = project_env
    owner, admin, sa = (
        env.make_user("developer"),
        env.make_user("admin"),
        env.make_user("super_admin"),
    )
    project = _project(env, owner)
    assert _probe(signed_in(env, admin), "read", project) == 404
    assert _probe(signed_in(env, sa), "manage", project) == 200
    assert _probe(signed_in(env, sa), "read", str(uuid.uuid4())) == 404  # still nothing to see


def test_role_and_project_access_must_both_allow(project_env: Env) -> None:
    """Owning a project does not grant an action the role lacks: user administration is
    refused for the owner of every project in the system."""
    env = project_env
    owner = env.make_user("developer")
    project = _project(env, owner)
    s = signed_in(env, owner)
    assert _probe(s, "manage", project) == 200  # scope + capability both allow
    assert s.request("GET", f"{API}/users").status_code == 403  # scope does not add capability
    env.pg.execute("UPDATE app_user.users SET is_active = false, deactivated_at = now()")
    assert _probe(s, "read", project) == 401  # nor does it survive deactivation


def test_csrf_protects_every_state_changing_admin_route(env: Env) -> None:
    sa, dev = env.make_user("super_admin"), env.make_user("developer")
    s = signed_in(env, sa)
    h = {"Origin": ORIGIN}
    assert s.client.post(f"{API}/admin/users", json=new_user_body(), headers=h).status_code == 403
    assert (
        s.client.patch(
            f"{API}/admin/users/{dev['id']}", json={"is_active": False}, headers=h
        ).status_code
        == 403
    )
    assert s.client.get(f"{API}/users", headers=h).status_code == 200


# ---- bootstrap ----------------------------------------------------------------------------


def test_bootstrap_super_admin_service(env: Env) -> None:
    from sentinel_ai.db.engine import create_session_factory

    ctx = RequestContext("cli", None, None)
    with create_session_factory(env.app.state.engine)() as db:
        user = user_service.bootstrap_super_admin(
            db, ctx, email="Root@Example.com", display_name="Root", password=NEW_PW
        )
        db.commit()
        assert user.email == "root@example.com" and user.role_name == "super_admin"
        with pytest.raises(ValueError, match="already exists"):
            user_service.bootstrap_super_admin(
                db, ctx, email="root@example.com", display_name="Root", password=NEW_PW
            )
        with pytest.raises(ValueError, match="password"):
            user_service.bootstrap_super_admin(
                db, ctx, email="x@example.com", display_name="X", password="short"
            )
    assert Session(env).login("root@example.com", NEW_PW).status_code == 200
    (row,) = env.audit("user.bootstrap_super_admin")
    assert row[0] == "success" and row[1] is None


def test_password_hash_is_never_returned_by_any_endpoint(env: Env) -> None:
    sa = env.make_user("super_admin")
    s = signed_in(env, sa)
    for url in (f"{API}/users", f"{API}/auth/me", f"{API}/auth/sessions"):
        text = s.request("GET", url).text
        assert "argon2" not in text and "password_hash" not in text
