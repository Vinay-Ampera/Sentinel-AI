import hashlib
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from conftest import Env, Session, signed_in
from fastapi.testclient import TestClient

from support import SAMPLE_PROJECT, make_zip

API = "/api/v1"
ZIP = {"Content-Type": "application/zip"}


@pytest.fixture
def penv(pg, tmp_path: Path) -> Iterator[Env]:  # type: ignore[no-untyped-def]
    e = Env(pg, artifact_storage_dir=tmp_path, upload_max_mb=1, zip_max_files=50)
    e.store = tmp_path  # type: ignore[attr-defined]
    with TestClient(e.app):
        yield e


def store_files(env: Env) -> list[Path]:
    root: Path = env.store  # type: ignore[attr-defined]
    return sorted(p for p in root.rglob("*") if p.is_file())


def mk_project(s: Session, name: str = "demo", app_type: str = "web_app") -> str:
    r = s.request("POST", f"{API}/projects", json={"name": name, "application_type": app_type})
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def upload(s: Session, pid: str, data: bytes, name: str = "src", **kw: object) -> object:
    return s.request(
        "POST", f"{API}/projects/{pid}/sources/zip", params={"name": name}, content=data,
        headers=kw.pop("headers", ZIP), **kw,
    )  # type: ignore[arg-type]  # fmt: skip


def count(env: Env, sql: str, *args: object) -> int:
    row = env.pg.execute(sql, args).fetchone()  # type: ignore[arg-type]
    assert row
    return int(row[0])


# ---- projects and ownership ----------------------------------------------------------


def test_project_lifecycle_and_validation(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    got = owner.request("GET", f"{API}/projects/{pid}").json()
    assert got["status"] == "active" and got["application_type"] == "web_app"
    listed = owner.request("GET", f"{API}/projects").json()["items"]
    assert [p["id"] for p in listed] == [pid] and listed[0]["your_access"] == "manage"

    bad_type = owner.request(
        "POST", f"{API}/projects", json={"name": "x", "application_type": "desktop"}
    )
    assert bad_type.status_code == 422
    assert (
        owner.request(
            "POST", f"{API}/projects", json={"name": "Demo", "application_type": "web_app"}
        ).status_code
        == 409
    )
    for body in (
        {"name": "", "application_type": "web_app"},
        {"name": "x", "application_type": "web_app", "owner_user_id": "1"},
    ):
        assert owner.request("POST", f"{API}/projects", json=body).status_code == 422

    renamed = owner.request("PATCH", f"{API}/projects/{pid}", json={"name": "Renamed"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Renamed"
    assert owner.request("POST", f"{API}/projects/{pid}/archive").json()["status"] == "archived"
    assert owner.request("GET", f"{API}/projects").json()["items"] == []
    assert len(owner.request("GET", f"{API}/projects?include_archived=true").json()["items"]) == 1
    assert (
        owner.request("PATCH", f"{API}/projects/{pid}", json={"name": "again"}).status_code == 409
    )
    assert {r[0] for r in penv.audit("project.create")} == {"success"}


def test_other_users_cannot_see_or_touch_a_project(penv: Env) -> None:
    alice, bob = signed_in(penv, penv.make_user()), signed_in(penv, penv.make_user())
    pid = mk_project(alice)
    assert upload(alice, pid, make_zip(SAMPLE_PROJECT)).status_code == 201  # type: ignore[attr-defined]
    sid = alice.request("GET", f"{API}/projects/{pid}/sources").json()["items"][0]["id"]
    aid = alice.request("POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}).json()[
        "id"
    ]

    assert bob.request("GET", f"{API}/projects").json()["items"] == []
    probes = [
        ("GET", f"{API}/projects/{pid}", {}),
        ("PATCH", f"{API}/projects/{pid}", {"json": {"name": "pwn"}}),
        ("POST", f"{API}/projects/{pid}/archive", {}),
        ("GET", f"{API}/projects/{pid}/members", {}),
        (
            "PUT",
            f"{API}/projects/{pid}/members/{uuid.uuid4()}",
            {"json": {"access_level": "manage"}},
        ),
        ("GET", f"{API}/projects/{pid}/sources", {}),
        ("DELETE", f"{API}/projects/{pid}/sources/{sid}", {}),
        ("POST", f"{API}/projects/{pid}/analyses", {"json": {"source_id": sid}}),
        ("GET", f"{API}/projects/{pid}/analyses", {}),
        ("GET", f"{API}/analyses/{aid}", {}),
    ]
    for method, url, kw in probes:
        r = bob.request(method, url, **kw)
        assert r.status_code == 404, (method, url, r.status_code)
        assert r.json()["error"]["code"] == "not_found"
    up = upload(bob, pid, make_zip(SAMPLE_PROJECT))
    assert up.status_code == 404  # type: ignore[attr-defined]
    assert count(penv, "SELECT count(*) FROM public.project_sources") == 1  # nothing added by Bob


def test_project_ids_are_not_proof_of_access_across_children(penv: Env) -> None:
    """A source or analysis id from project A cannot be used through project B."""
    alice = signed_in(penv, penv.make_user())
    a, b = mk_project(alice, "a"), mk_project(alice, "b")
    upload(alice, a, make_zip(SAMPLE_PROJECT))
    sid = alice.request("GET", f"{API}/projects/{a}/sources").json()["items"][0]["id"]
    r = alice.request("POST", f"{API}/projects/{b}/analyses", json={"source_id": sid})
    assert r.status_code == 404
    assert alice.request("DELETE", f"{API}/projects/{b}/sources/{sid}").status_code == 404
    assert alice.request("GET", f"{API}/projects/{b}/sources").json()["items"] == []


def test_membership_levels_gate_each_action(penv: Env) -> None:
    owner_u = penv.make_user()
    reader_u, runner_u, manager_u = (penv.make_user() for _ in range(3))
    owner = signed_in(penv, owner_u)
    pid = mk_project(owner)
    upload(owner, pid, make_zip(SAMPLE_PROJECT))
    sid = owner.request("GET", f"{API}/projects/{pid}/sources").json()["items"][0]["id"]
    for user, level in ((reader_u, "read"), (runner_u, "run"), (manager_u, "manage")):
        r = owner.request(
            "PUT", f"{API}/projects/{pid}/members/{user['id']}", json={"access_level": level}
        )
        assert r.status_code == 204
    reader, runner, manager = (signed_in(penv, u) for u in (reader_u, runner_u, manager_u))

    assert reader.request("GET", f"{API}/projects/{pid}/sources").status_code == 200
    assert reader.request("GET", f"{API}/projects/{pid}").status_code == 200
    analyze = {"json": {"source_id": sid}}
    assert reader.request("POST", f"{API}/projects/{pid}/analyses", **analyze).status_code == 403
    assert upload(reader, pid, make_zip(SAMPLE_PROJECT)).status_code == 403  # type: ignore[attr-defined]
    assert reader.request("PATCH", f"{API}/projects/{pid}", json={"name": "x"}).status_code == 403
    assert reader.request("GET", f"{API}/projects/{pid}/members").status_code == 403

    assert runner.request("POST", f"{API}/projects/{pid}/analyses", **analyze).status_code == 201
    assert upload(runner, pid, make_zip(SAMPLE_PROJECT)).status_code == 403  # type: ignore[attr-defined]
    assert runner.request("DELETE", f"{API}/projects/{pid}/sources/{sid}").status_code == 403

    assert upload(manager, pid, make_zip(SAMPLE_PROJECT), name="by-manager").status_code == 201  # type: ignore[attr-defined]
    members = manager.request("GET", f"{API}/projects/{pid}/members").json()["items"]
    assert {m["access_level"] for m in members} == {"read", "run", "manage"}

    # Revoking membership removes access immediately.
    assert (
        owner.request("DELETE", f"{API}/projects/{pid}/members/{reader_u['id']}").status_code == 204
    )
    assert reader.request("GET", f"{API}/projects/{pid}").status_code == 404
    actions = {r[0] for r in penv.pg.execute("SELECT action FROM public.audit_events").fetchall()}
    assert {
        "project.member_set",
        "project.member_remove",
        "source.create",
        "analysis.run",
    } <= actions


def test_member_management_rules(penv: Env) -> None:
    owner_u, other = penv.make_user(), penv.make_user()
    inactive = penv.make_user(is_active=False)
    owner = signed_in(penv, owner_u)
    pid = mk_project(owner)
    put = lambda uid, level: owner.request(  # noqa: E731
        "PUT", f"{API}/projects/{pid}/members/{uid}", json={"access_level": level}
    )
    assert put(owner_u["id"], "read").status_code == 409  # owner is not a member
    assert put(other["id"], "admin").status_code == 422
    assert put(uuid.uuid4(), "read").status_code == 404
    assert put(inactive["id"], "read").status_code == 404
    assert (
        put(other["id"], "run").status_code == 204 and put(other["id"], "read").status_code == 204
    )
    assert [
        m["access_level"]
        for m in owner.request("GET", f"{API}/projects/{pid}/members").json()["items"]
    ] == ["read"]
    assert (
        owner.request("DELETE", f"{API}/projects/{pid}/members/{uuid.uuid4()}").status_code == 404
    )


def test_admin_has_no_implicit_access_and_super_admin_access_is_audited(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    admin = signed_in(penv, penv.make_user("admin"))
    sa = signed_in(penv, penv.make_user("super_admin"))
    assert admin.request("GET", f"{API}/projects/{pid}").status_code == 404
    assert admin.request("GET", f"{API}/projects").json()["items"] == []
    assert sa.request("GET", f"{API}/projects/{pid}").status_code == 200
    assert [p["id"] for p in sa.request("GET", f"{API}/projects").json()["items"]] == [pid]
    assert (
        count(
            penv,
            "SELECT count(*) FROM public.audit_events WHERE action = 'project.privileged_access'",
        )
        == 1
    )
    assert (
        count(penv, "SELECT count(*) FROM public.audit_events WHERE action = 'project.list_all'")
        == 1
    )


# ---- upload validation ------------------------------------------------------------------


def test_valid_upload_is_stored_hashed_and_never_extracted(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    data = make_zip(SAMPLE_PROJECT)
    r = upload(owner, pid, data, name="my source")
    assert r.status_code == 201  # type: ignore[attr-defined]
    body = r.json()  # type: ignore[attr-defined]
    assert body["sha256"] == hashlib.sha256(data).hexdigest() and body["size_bytes"] == len(data)
    assert body["source_type"] == "zip_upload" and "storage" not in json.dumps(body)
    files = store_files(penv)
    assert len(files) == 1 and files[0].suffix == ".zip" and files[0].read_bytes() == data
    assert not (files[0].parent / "app").exists()  # archive contents were not extracted
    assert not os.access(files[0], os.X_OK)
    (kind, status) = penv.pg.execute(
        "SELECT kind, validation_status FROM public.artifacts"
    ).fetchone()  # type: ignore[misc]
    assert (kind, status) == ("upload", "accepted")


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        (b"", 422, "invalid_archive"),
        (b"just text, not a zip", 422, "invalid_archive"),
        (make_zip({"a": "b"})[:25], 422, "invalid_archive"),
        (make_zip({"../escape.py": "x"}), 422, "unsafe_path"),
        (make_zip({"/abs/path.py": "x"}), 422, "unsafe_path"),
        (make_zip({"dir/": ""}), 422, "empty_archive"),
        (make_zip({"z.bin": b"\0" * (4 * 1024 * 1024)}), 422, "compression_bomb"),
        (make_zip({f"f{i}.txt": "x" for i in range(60)}), 413, "too_many_files"),
    ],
)  # fmt: skip
def test_invalid_archives_are_rejected_safely(
    penv: Env, payload: bytes, status: int, code: str
) -> None:
    owner = signed_in(penv, signed_user := penv.make_user())
    pid = mk_project(owner)
    r = upload(owner, pid, payload)
    assert (r.status_code, r.json()["error"]["code"]) == (status, code)  # type: ignore[attr-defined]
    assert store_files(penv) == []  # nothing stored, temp file removed
    assert count(penv, "SELECT count(*) FROM public.project_sources") == 0
    assert count(penv, "SELECT count(*) FROM public.artifacts") == 0
    failures = [row for row in penv.audit("source.upload") if row[0] == "failure"]
    if payload:
        assert (
            failures
            and failures[-1][2]["reason"] == code
            and str(failures[-1][1]) == signed_user["id"]
        )


def test_oversized_uploads_are_rejected_before_and_during_streaming(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    big = os.urandom(1024 * 1024 + 4096)  # limit is 1 MiB in this fixture
    declared = upload(owner, pid, big)
    assert (declared.status_code, declared.json()["error"]["code"]) == (413, "payload_too_large")  # type: ignore[attr-defined]

    def chunks() -> Iterator[bytes]:  # no Content-Length: enforced while streaming
        for _ in range(40):
            yield os.urandom(32 * 1024)

    streamed = owner.request(
        "POST",
        f"{API}/projects/{pid}/sources/zip",
        params={"name": "s"},
        content=chunks(),
        headers=ZIP,
    )
    assert (streamed.status_code, streamed.json()["error"]["code"]) == (413, "payload_too_large")
    assert store_files(penv) == [] and count(penv, "SELECT count(*) FROM public.artifacts") == 0


def test_upload_content_type_name_and_csrf_checks(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    data = make_zip(SAMPLE_PROJECT)
    wrong = upload(owner, pid, data, headers={"Content-Type": "text/html"})
    assert wrong.status_code == 415  # type: ignore[attr-defined]
    assert upload(owner, pid, data, name="bad\x01name").status_code == 422  # type: ignore[attr-defined]
    no_csrf = owner.request(
        "POST",
        f"{API}/projects/{pid}/sources/zip",
        csrf=False,
        params={"name": "s"},
        content=data,
        headers=ZIP,
    )
    assert no_csrf.status_code == 403, no_csrf.text
    assert no_csrf.json()["error"]["code"] == "csrf_failed"
    cross = upload(owner, pid, data, headers={**ZIP, "Origin": "https://evil.example"})
    assert cross.status_code == 403  # type: ignore[attr-defined]
    anon = Session(penv).client.post(
        f"{API}/projects/{pid}/sources/zip", params={"name": "s"}, content=data, headers=ZIP
    )
    assert anon.status_code == 401
    assert (
        store_files(penv) == [] and count(penv, "SELECT count(*) FROM public.project_sources") == 0
    )


def test_archived_project_rejects_writes(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    upload(owner, pid, make_zip(SAMPLE_PROJECT))
    sid = owner.request("GET", f"{API}/projects/{pid}/sources").json()["items"][0]["id"]
    owner.request("POST", f"{API}/projects/{pid}/archive")
    assert upload(owner, pid, make_zip(SAMPLE_PROJECT)).status_code == 409  # type: ignore[attr-defined]
    assert (
        owner.request("POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}).status_code
        == 409
    )
    assert (
        owner.request("GET", f"{API}/projects/{pid}/sources").status_code == 200
    )  # reads still work
    assert len(store_files(penv)) == 1


# ---- analysis ----------------------------------------------------------------------------


def _analysed(env: Env) -> tuple[Session, str, str, dict]:  # type: ignore[type-arg]
    owner = signed_in(env, env.make_user())
    pid = mk_project(owner)
    upload(owner, pid, make_zip(SAMPLE_PROJECT))
    sid = owner.request("GET", f"{API}/projects/{pid}/sources").json()["items"][0]["id"]
    r = owner.request("POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid})
    assert r.status_code == 201, r.text
    return owner, pid, sid, r.json()


def test_analysis_result_separates_facts_inferences_and_gaps_and_is_persisted(penv: Env) -> None:
    owner, pid, sid, snap = _analysed(penv)
    assert snap["status"] == "completed" and snap["error_summary"] is None
    result = snap["result"]
    assert set(result) >= {"facts", "inferences", "gaps", "warnings", "analyzer_version"}
    assert result["executed_code"] is False
    assert "fastapi" in [f["name"] for f in result["facts"]["frameworks"]]
    assert any(g["id"] == "runtime_behavior" for g in result["gaps"])
    assert "do-not-store-me" not in json.dumps(snap)

    fetched = owner.request("GET", f"{API}/analyses/{snap['id']}").json()
    assert fetched == snap  # visible and identical after persistence
    assert (
        owner.request("GET", f"{API}/projects/{pid}/analyses").json()["items"][0]["id"]
        == snap["id"]
    )
    sha = hashlib.sha256(make_zip(SAMPLE_PROJECT)).hexdigest()
    assert snap["content_sha256"] == sha
    (stored,) = penv.pg.execute("SELECT detected FROM public.analysis_snapshots").fetchone()  # type: ignore[misc]
    assert stored == result


def test_repeated_analysis_is_identical_and_each_run_is_recorded(penv: Env) -> None:
    owner, pid, sid, first = _analysed(penv)
    second = owner.request("POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}).json()
    assert second["id"] != first["id"]
    assert (
        second["result"] == first["result"] and second["content_sha256"] == first["content_sha256"]
    )
    assert len(owner.request("GET", f"{API}/projects/{pid}/analyses").json()["items"]) == 2


def test_tampered_or_missing_archive_yields_failed_snapshot_not_a_result(penv: Env) -> None:
    owner, pid, sid, _ = _analysed(penv)
    (stored,) = store_files(penv)
    stored.write_bytes(make_zip({"evil.py": "x"}))  # same path, different bytes
    tampered = owner.request(
        "POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}
    ).json()
    assert tampered["status"] == "failed" and tampered["result"] == {}
    assert tampered["error_summary"].startswith("integrity_mismatch")
    stored.unlink()
    missing = owner.request(
        "POST", f"{API}/projects/{pid}/analyses", json={"source_id": sid}
    ).json()
    assert missing["status"] == "failed" and missing["error_summary"].startswith("artifact_missing")
    assert {r[0] for r in penv.audit("analysis.run")} == {"success", "failure"}


def test_analysis_input_validation(penv: Env) -> None:
    owner, pid, sid, _ = _analysed(penv)
    url = f"{API}/projects/{pid}/analyses"
    assert owner.request("POST", url, json={}).status_code == 422
    assert owner.request("POST", url, json={"source_id": "not-a-uuid"}).status_code == 422
    assert owner.request("POST", url, json={"source_id": str(uuid.uuid4())}).status_code == 404
    assert owner.request("POST", url, json={"source_id": sid, "extra": 1}).status_code == 422
    assert owner.request("DELETE", f"{API}/projects/{pid}/sources/{sid}").status_code == 204
    r = owner.request("POST", url, json={"source_id": sid})
    assert (r.status_code, r.json()["error"]["code"]) == (409, "source_inactive")
    assert owner.request("GET", f"{API}/analyses/{uuid.uuid4()}").status_code == 404


SRC = f"{API}/projects"


def _register(s: Session, pid: str, **body: object):  # type: ignore[no-untyped-def]
    return s.request("POST", f"{SRC}/{pid}/sources", json={"name": "src", **body})


def test_git_localhost_and_remote_sources_are_registered_without_network(
    penv: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    import socket

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("network/DNS access attempted")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    git = _register(
        owner,
        pid,
        source_type="git_repository",
        git_url="https://github.com/org/repo.git",
        git_ref="main",
    )
    local = _register(owner, pid, source_type="localhost_url", target_url="http://localhost:3000")
    remote = _register(
        owner,
        pid,
        source_type="remote_url",
        target_url="https://staging.example.com",
        environment="staging",
    )
    assert [r.status_code for r in (git, local, remote)] == [201, 201, 201]
    assert git.json()["git_ref"] == "main" and git.json()["target_url"] is None
    assert local.json()["environment"] == "local" and remote.json()["environment"] == "staging"
    listed = owner.request("GET", f"{SRC}/{pid}/sources").json()["items"]
    assert {i["source_type"] for i in listed} == {"git_repository", "localhost_url", "remote_url"}
    assert (
        count(penv, "SELECT count(*) FROM public.target_authorizations") == 0
    )  # nothing authorized
    assert (
        count(penv, "SELECT count(*) FROM public.audit_events WHERE action = 'source.create'") == 3
    )


def test_url_source_validation_rejections_are_audited(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    cases = [
        (
            {"source_type": "git_repository", "git_url": "https://u:p@github.com/o/r"},
            "credentials_in_url",
        ),
        (
            {"source_type": "git_repository", "git_url": "http://github.com/o/r"},
            "unsupported_scheme",
        ),
        ({"source_type": "git_repository", "git_url": "https://10.0.0.1/o/r"}, "blocked_host"),
        (
            {
                "source_type": "git_repository",
                "git_url": "https://github.com/o/r",
                "git_ref": "--upload-pack=x",
            },
            "invalid_ref",
        ),
        ({"source_type": "git_repository"}, "invalid_url"),
        ({"source_type": "localhost_url", "target_url": "http://evil.com"}, "not_localhost"),
        (
            {
                "source_type": "remote_url",
                "target_url": "http://169.254.169.254/",
                "environment": "development",
            },
            "blocked_host",
        ),
        ({"source_type": "remote_url", "target_url": "https://example.com"}, "invalid_url"),
        (
            {
                "source_type": "remote_url",
                "target_url": "https://example.com",
                "environment": "production",
            },
            "production_blocked",
        ),
    ]
    for body, expected in cases:
        r = _register(owner, pid, **body)
        assert (r.status_code, r.json()["error"]["code"]) == (422, expected), body
    for body in (
        {"source_type": "ftp"},
        {"source_type": "zip_upload"},
        {
            "source_type": "localhost_url",
            "target_url": "http://localhost",
            "git_url": "https://github.com/o/r",
        },
        {
            "source_type": "git_repository",
            "git_url": "https://github.com/o/r",
            "environment": "staging",
        },
    ):
        assert _register(owner, pid, **body).status_code == 422
    assert (
        owner.request(
            "POST",
            f"{SRC}/{pid}/sources",
            json={
                "source_type": "localhost_url",
                "target_url": "http://localhost",
                "name": "x",
                "id": "1",
            },
        ).status_code
        == 422
    )
    assert count(penv, "SELECT count(*) FROM public.project_sources") == 0
    rows = penv.audit("source.create")
    assert {r[0] for r in rows} == {"failure", "denied"}
    assert any(r[0] == "denied" and r[2]["reason"] == "production_blocked" for r in rows)


def test_url_source_registration_is_access_controlled(penv: Env) -> None:
    owner_u, reader_u, stranger_u = penv.make_user(), penv.make_user(), penv.make_user()
    owner, reader, stranger = (signed_in(penv, u) for u in (owner_u, reader_u, stranger_u))
    pid = mk_project(owner)
    owner.request("PUT", f"{SRC}/{pid}/members/{reader_u['id']}", json={"access_level": "run"})
    body = {"source_type": "git_repository", "git_url": "https://github.com/o/r"}
    assert _register(reader, pid, **body).status_code == 403
    assert _register(stranger, pid, **body).status_code == 404
    assert _register(Session(penv), pid, **body).status_code == 401
    no_csrf = owner.request("POST", f"{SRC}/{pid}/sources", csrf=False, json={"name": "x", **body})
    assert no_csrf.status_code == 403
    owner.request("POST", f"{SRC}/{pid}/archive")
    assert _register(owner, pid, **body).status_code == 409
    assert count(penv, "SELECT count(*) FROM public.project_sources") == 0


def test_non_zip_sources_cannot_be_analysed_yet_and_say_why(penv: Env) -> None:
    owner = signed_in(penv, penv.make_user())
    pid = mk_project(owner)
    expectations = {
        "git_repository": ({"git_url": "https://github.com/o/r"}, "sandbox"),
        "localhost_url": ({"target_url": "http://localhost:3000"}, "Q26"),
        "remote_url": (
            {"target_url": "https://dev.example.com", "environment": "development"},
            "authorization",
        ),
    }
    for source_type, (extra, hint) in expectations.items():
        sid = _register(owner, pid, source_type=source_type, **extra).json()["id"]
        r = owner.request("POST", f"{SRC}/{pid}/analyses", json={"source_id": sid})
        assert (r.status_code, r.json()["error"]["code"]) == (422, "analysis_not_available")
        assert hint in r.json()["error"]["message"]
    assert count(penv, "SELECT count(*) FROM public.analysis_snapshots") == 0  # no fake results
