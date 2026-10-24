"""Stage 12 integration (ADR-0011): ingest keys, ingestion limits and redaction, grouping, the
deterministic alert rules, correlation, alert authorization and audit, the telemetry disclosure,
internal failure alerts, the failure-to-test loop with the fake provider, and retention.

Everything runs against a disposable database; no network, no real model, no real key."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_agent_workflows import Lab, draft, lab, short, sql  # noqa: F401 (lab is a fixture)
from test_findings import World, fr, scan
from test_plans_api import API, add_member, user
from test_runs_jobs import factory, make_env  # noqa: F401 (a fixture)

from sentinel_ai.api.observability import IngestLimits
from sentinel_ai.services import alerts, event_retention, ingestion
from sentinel_ai.services.event_redaction import EventRedactor

INGEST = f"{API}/ingest/events"


def ev(message: str = "boom", **over: Any) -> dict[str, Any]:
    return {
        "level": "error",
        "service": "api",
        "environment": "staging",
        "message": message,
        **over,
    }


def tweak(lab: Lab, **settings: Any) -> None:
    """Change settings on the running app (and rebuild the in-process limiters)."""
    new = lab.e.app.state.settings.model_copy(update=settings)
    lab.e.app.state.settings = new
    lab.e.app.state.ingest_limits = IngestLimits(new)


def policy(lab: Lab, key: str, value: Any, session: Any = None) -> Any:
    s = session or lab.s
    return s.request("PUT", f"{API}/projects/{lab.pid}/policies/{key}", json={"value": value})


def enable(lab: Lab) -> None:
    assert policy(lab, "observability_ingest", {"enabled": True}).status_code == 200


def new_key(lab: Lab, label: str = "app", session: Any = None, pid: str | None = None) -> Any:
    return (session or lab.s).request(
        "POST", f"{API}/projects/{pid or lab.pid}/ingest-keys", json={"label": label}
    )


def key(lab: Lab) -> str:
    r = new_key(lab)
    assert r.status_code == 201, r.text
    return str(r.json()["key"])


def push(lab: Lab, raw_key: str | None, events: list[Any], **kw: Any) -> Any:
    headers = {"Authorization": f"Bearer {raw_key}"} if raw_key else {}
    c = TestClient(lab.e.app)  # no context manager: keep the app state; no cookies either
    return c.post(INGEST, json={"events": events}, headers=headers, **kw)


def ready(lab: Lab) -> str:
    enable(lab)
    return key(lab)


def alerts_of(lab: Lab, **params: Any) -> list[dict]:
    r = lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts", params=params)
    assert r.status_code == 200, r.text
    return list(r.json()["items"])


def rule_alerts(lab: Lab, rule: str) -> list[dict]:
    return [a for a in alerts_of(lab) if a["rule"] == rule]


def svc_ingest(lab: Lab, events: list[Any], now: datetime) -> Any:
    row = sql(lab.e, "SELECT id FROM public.ingest_keys WHERE project_id = %s LIMIT 1", lab.pid)[0]
    auth = ingestion.KeyAuth(row[0], uuid.UUID(lab.pid))
    with factory(lab.e)() as db:
        result = ingestion.ingest_batch(
            db, lab.e.app.state.settings, EventRedactor(), auth, events, now=now
        )
        db.commit()
    return result


def group_id(lab: Lab) -> str:
    return str(sql(lab.e, "SELECT id FROM public.event_groups WHERE project_id = %s ORDER BY first_seen LIMIT 1", lab.pid)[0][0])  # fmt: skip


# ---- keys ---------------------------------------------------------------------------------


def test_keys_are_shown_once_hashed_at_rest_scoped_and_managed_by_managers(lab: Lab) -> None:
    r = new_key(lab, "  prod   app ")
    assert r.status_code == 201
    created = r.json()
    raw = created["key"]
    assert raw.startswith("sai_ing_" + created["key_id"] + "_") and created["label"] == "prod app"
    listing = lab.s.request("GET", f"{API}/projects/{lab.pid}/ingest-keys").json()["items"]
    assert "key" not in listing[0] and "key_hash" not in json.dumps(listing)
    stored = sql(lab.e, "SELECT key_hash, key_id FROM public.ingest_keys WHERE project_id = %s", lab.pid)[0]  # fmt: skip
    assert raw.encode() not in bytes(stored[0]) and len(bytes(stored[0])) == 32
    dumped = sql(lab.e, "SELECT row_to_json(k)::text FROM public.ingest_keys k")[0][0]
    assert raw.split("_", 3)[-1] not in dumped  # the secret part is nowhere in the table

    runner, rs = user(lab.e)
    add_member(lab.s, lab.pid, runner, "run")
    reader, rds = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    _, stranger = user(lab.e)
    assert new_key(lab, session=rs).status_code == 403  # run access is not manage
    assert new_key(lab, session=rds).status_code == 403
    assert new_key(lab, session=stranger).status_code == 404
    assert rs.request("GET", f"{API}/projects/{lab.pid}/ingest-keys").status_code == 403

    assert lab.e.audit("ingest_key.create")  # audited, and the audit detail has no key
    assert raw not in json.dumps(sql(lab.e, "SELECT detail::text FROM public.audit_events WHERE action = 'ingest_key.create'"))  # fmt: skip

    kid = created["id"]
    assert lab.s.request("DELETE", f"{API}/projects/{lab.pid}/ingest-keys/{kid}").json()["status"] == "revoked"  # fmt: skip
    assert lab.s.request("DELETE", f"{API}/projects/{lab.pid}/ingest-keys/{kid}").status_code == 409
    other = World(lab.e)
    assert other.s.request("DELETE", f"{API}/projects/{other.pid}/ingest-keys/{kid}").status_code == 404  # fmt: skip
    assert lab.e.audit("ingest_key.revoke")


def test_key_count_and_lifetime_are_bounded(lab: Lab) -> None:
    tweak(lab, ingest_keys_per_project=2)
    assert new_key(lab).status_code == 201 and new_key(lab).status_code == 201
    assert new_key(lab).status_code == 409
    for days in (0, 366):
        bad = lab.s.request("POST", f"{API}/projects/{lab.pid}/ingest-keys", json={"label": "x", "expires_in_days": days})  # fmt: skip
        assert bad.status_code == 422
    assert lab.s.request("POST", f"{API}/projects/{lab.pid}/ingest-keys", json={"label": "  "}).status_code == 422  # fmt: skip


def test_ingestion_is_off_by_default_and_only_managers_switch_it(lab: Lab) -> None:
    raw = key(lab)
    r = push(lab, raw, [ev()])
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ingest_disabled")
    assert sql(lab.e, "SELECT count(*) FROM public.event_groups") == [(0,)]
    runner, rs = user(lab.e)
    add_member(lab.s, lab.pid, runner, "run")
    assert policy(lab, "observability_ingest", {"enabled": True}, rs).status_code == 403
    assert policy(lab, "observability_ingest", {"enabled": "yes"}).status_code == 422
    enable(lab)
    assert push(lab, raw, [ev()]).status_code == 202
    assert policy(lab, "observability_ingest", {"enabled": False}).status_code == 200
    assert push(lab, raw, [ev()]).status_code == 403  # switching off takes effect at once


def test_bad_credentials_all_look_the_same_and_cookies_do_not_authenticate(lab: Lab) -> None:
    enable(lab)
    good = key(lab)
    revoked = key(lab)
    rid = lab.s.request("GET", f"{API}/projects/{lab.pid}/ingest-keys").json()["items"]
    revoked_id = next(k["id"] for k in rid if revoked.startswith("sai_ing_" + k["key_id"]))
    lab.s.request("DELETE", f"{API}/projects/{lab.pid}/ingest-keys/{revoked_id}")
    expired = key(lab)
    exp_id = expired[8:20]
    sql(lab.e, "UPDATE public.ingest_keys SET created_at = now() - interval '3 days', expires_at = now() - interval '1 day' WHERE key_id = %s", exp_id)  # fmt: skip
    wrong_secret = good[:-3] + ("aaa" if not good.endswith("aaa") else "bbb")
    bodies = set()
    for candidate in (
        None,
        "nonsense",
        "sai_ing_000000000000_" + "x" * 43,
        revoked,
        expired,
        wrong_secret,
    ):
        r = push(lab, candidate, [ev()])
        assert r.status_code == 401, candidate
        err = r.json()["error"]
        bodies.add((err["code"], err["message"]))
        assert r.headers["www-authenticate"] == "Bearer"
    assert len(bodies) == 1  # nothing tells which part was wrong
    # a signed-in person's session cookie is not a credential here
    r = lab.s.request("POST", INGEST, json={"events": [ev()]})
    assert r.status_code == 401
    assert push(lab, good, [ev()]).status_code == 202
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(1,)]


def test_a_key_works_only_for_its_own_project(lab: Lab) -> None:
    other = World(lab.e)
    lab.s.request("PUT", f"{API}/projects/{lab.pid}/policies/observability_ingest", json={"value": {"enabled": True}})  # fmt: skip
    other.s.request("PUT", f"{API}/projects/{other.pid}/policies/observability_ingest", json={"value": {"enabled": True}})  # fmt: skip
    k_other = new_key(lab, session=other.s, pid=other.pid).json()["key"]
    assert push(lab, k_other, [ev("from other project")]).status_code == 202
    assert sql(lab.e, "SELECT count(*) FROM public.event_groups WHERE project_id = %s", lab.pid) == [(0,)]  # fmt: skip
    assert sql(lab.e, "SELECT count(*) FROM public.event_groups WHERE project_id = %s", other.pid) == [(1,)]  # fmt: skip
    # and the key opens no other route
    for method, url in (("GET", f"/projects/{other.pid}/alerts"), ("GET", f"/projects/{other.pid}/ingest-keys")):  # fmt: skip
        with TestClient(lab.e.app) as c:
            assert c.request(method, f"{API}{url}", headers={"Authorization": f"Bearer {k_other}"}).status_code == 401  # fmt: skip


# ---- limits and drops ---------------------------------------------------------------------


def test_request_shape_limits_and_per_event_drops(lab: Lab) -> None:
    raw = ready(lab)
    with TestClient(lab.e.app) as c:
        h = {"Authorization": f"Bearer {raw}"}
        assert c.post(INGEST, content=b"not json", headers=h).status_code == 422
        assert c.post(INGEST, json=[ev()], headers=h).status_code == 422
        assert c.post(INGEST, json={"events": []}, headers=h).status_code == 422
        assert c.post(INGEST, json={"events": [ev()], "extra": 1}, headers=h).status_code == 422
        assert c.post(INGEST, json={"events": [ev()] * 101}, headers=h).status_code == 422
        big = json.dumps({"events": [ev("x" * 2000)] * 200}).encode()
        assert len(big) > 256 * 1024
        assert c.post(INGEST, content=big, headers={**h, "Content-Type": "application/json"}).status_code == 413  # fmt: skip
    mixed = [ev("kept"), {"level": "error"}, ev("noise", level="debug"), ev("info", level="info"),
             ev("x", unknown=1), "not an object", ev("also kept", level="warning")]  # fmt: skip
    r = push(lab, raw, mixed)
    assert r.status_code == 202
    assert r.json() == {"accepted": 2, "dropped": {"invalid_schema": 3, "level_below_threshold": 2}}
    stats = sql(lab.e, "SELECT accepted, dropped::text FROM public.ingest_stats WHERE project_id = %s", lab.pid)[0]  # fmt: skip
    assert stats[0] == 2 and json.loads(stats[1])["invalid_schema"] == 3


def test_quota_and_group_cap_are_enforced_counted_and_alerted(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, event_daily_quota=3, event_max_groups_per_project=2)
    r = push(lab, raw, [ev("one"), ev("two"), ev("three"), ev("four")])
    assert r.json() == {"accepted": 3, "dropped": {"quota": 1, "group_cap": 1}}
    groups = sql(lab.e, "SELECT is_overflow, total_count FROM public.event_groups WHERE project_id = %s ORDER BY is_overflow", lab.pid)  # fmt: skip
    assert groups == [(False, 1), (False, 1), (True, 1)]  # the third distinct error overflowed
    drop = rule_alerts(lab, "ingest_dropping")
    assert len(drop) == 1 and drop[0]["measured"] == {"quota": 1, "group_cap": 1}
    assert push(lab, raw, [ev("five")]).json()["dropped"] == {"quota": 1}  # still the same day


def test_secrets_are_redacted_before_anything_is_stored(lab: Lab) -> None:
    raw = ready(lab)
    secret_event = ev(
        "login failed ada@example.com password=hunter2hunter2",
        stack='Traceback\n  File "/a.py", line 1, in f\nAuthorization: Bearer abcdefghijklmnop0123',
        error_type="AuthError", release="v1 token=zzzzzzzzzz",
        attributes={"password": "plain", "note": "key AIza" + "B" * 35, "count": 3},
    )  # fmt: skip
    assert push(lab, raw, [secret_event]).status_code == 202
    row = sql(lab.e, "SELECT message, stack, release, attributes::text, redactions::text FROM public.events")[0]  # fmt: skip
    stored = " ".join(str(x) for x in row)
    for secret in ("ada@example.com", "hunter2hunter2", "abcdefghijklmnop0123", "zzzzzzzzzz", "plain", "AIzaBBBB"):  # fmt: skip
        assert secret not in stored
    assert "[REDACTED" in row[0] and json.loads(row[4])  # counts kept, values not
    assert json.loads(row[3])["count"] == 3
    norm = sql(lab.e, "SELECT message_norm FROM public.event_groups")[0][0]
    assert "hunter2" not in norm and "ada@" not in norm
    # a configured platform secret never lands in a row either
    cfg = lab.e.app.state.settings
    assert push(lab, raw, [ev(f"leak {cfg.pepper()}")]).status_code == 202
    assert cfg.pepper() not in " ".join(str(r[0]) for r in sql(lab.e, "SELECT message FROM public.events"))  # fmt: skip


# ---- grouping and samples ---------------------------------------------------------------------


def test_equal_errors_group_and_samples_stay_capped(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, event_samples_per_group=6)
    assert push(lab, raw, [ev(f"User {i} not found") for i in range(12)]).json()["accepted"] == 12
    g = sql(lab.e, "SELECT total_count, has_stack FROM public.event_groups")
    assert g == [(12, False)]
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(6,)]  # first 5 + latest 1
    texts = [
        r[0] for r in sql(lab.e, "SELECT message FROM public.events ORDER BY received_at, seq")
    ]
    assert texts[0] == "User 0 not found" and texts[-1] == "User 11 not found"
    assert sql(lab.e, "SELECT sum(count) FROM public.event_buckets") == [(12,)]
    detail = lab.s.request("GET", f"{API}/projects/{lab.pid}/event-groups/{group_id(lab)}").json()
    assert detail["total_count"] == 12 and len(detail["samples"]) == 6
    assert detail["samples"][0]["reported_by"] == "application" and detail["limits"]
    assert "<n>" in detail["message"]  # the pattern, not one sample


def test_timestamps_are_advisory_only(lab: Lab) -> None:
    raw = ready(lab)
    old = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    near = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    assert push(lab, raw, [ev("a", timestamp=old), ev("b", timestamp=future), ev("c", timestamp=near)]).json()["accepted"] == 3  # fmt: skip
    rows = {r[0]: r[1:] for r in sql(lab.e, "SELECT message, timestamp_untrusted, client_timestamp IS NULL, received_at > now() - interval '1 minute' FROM public.events")}  # fmt: skip
    assert rows["a"] == (True, True, True) and rows["b"] == (True, True, True)
    assert rows["c"] == (False, False, True)  # kept for display; received_at is still server time


# ---- alert rules ------------------------------------------------------------------------------


def test_new_error_group_alerts_once_with_evidence_and_no_cause_claim(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("db down", error_type="OperationalError")] * 2)
    assert rule_alerts(lab, "new_error_group") == []  # 2 of the 3 needed
    push(lab, raw, [ev("db down", error_type="OperationalError")])
    (a,) = rule_alerts(lab, "new_error_group")
    assert (a["severity"], a["status"], a["source"], a["confidence"]) == ("medium", "open", "external", "observed")  # fmt: skip
    assert a["cause_status"] == "not_investigated" and a["occurrences"] == 1
    assert a["measured"]["events"] == 3 and a["measured"]["service"] == "api"
    gid = group_id(lab)
    assert a["evidence"] == {"group_id": gid} and a["group_id"] == gid
    assert "reason" not in json.dumps(a["measured"]).lower() and "cause" not in a["next_action"].lower().replace("cause_status", "")  # fmt: skip
    push(lab, raw, [ev("db down", error_type="OperationalError")] * 4)
    (again,) = rule_alerts(lab, "new_error_group")
    assert again["id"] == a["id"] and again["occurrences"] > 1  # one open alert per subject
    detail = lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts/{a['id']}").json()
    assert (
        detail["history"][0]["action"] == "created"
        and "no cause is claimed" in detail["cause_note"]
    )
    assert detail["telemetry"]["has_events"] is True and detail["group"]["id"] == gid
    assert lab.e.audit("alert.create")


def test_fatal_alerts_at_once_and_warnings_never_raise_error_alerts(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("disk gone", level="warning")] * 10)
    assert alerts_of(lab) == []
    push(lab, raw, [ev("kernel panic", level="fatal")])
    (a,) = alerts_of(lab)
    assert (a["rule"], a["severity"]) == ("new_error_group", "high")


def test_thresholds_are_configurable_within_bounds(lab: Lab) -> None:
    raw = ready(lab)
    assert policy(lab, "alert_thresholds", {"new_group_events": 0}).status_code == 422
    assert policy(lab, "alert_thresholds", {"bogus": 1}).status_code == 422
    assert policy(lab, "alert_thresholds", {"new_group_events": 1}).status_code == 200
    push(lab, raw, [ev("single")])
    assert [a["rule"] for a in alerts_of(lab)] == ["new_error_group"]
    runner, rs = user(lab.e)
    add_member(lab.s, lab.pid, runner, "run")
    assert policy(lab, "alert_thresholds", {"new_group_events": 5}, rs).status_code == 403


def test_recurrence_reopens_the_resolved_alert_and_keeps_history(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("flaky dependency")] * 3)
    (a,) = alerts_of(lab)
    url = f"{API}/projects/{lab.pid}/alerts/{a['id']}"
    assert (
        lab.s.request("POST", f"{url}/resolve", json={"note": "fixed upstream"}).status_code == 200
    )
    push(lab, raw, [ev("flaky dependency")])
    (back,) = alerts_of(lab)
    assert back["id"] == a["id"] and back["status"] == "open" and back["closed_at"] is None
    actions = [h["action"] for h in lab.s.request("GET", url).json()["history"]]
    assert actions == ["created", "resolved", "reopened"]
    assert lab.e.audit("alert.reopen")


def test_spike_uses_the_baseline_when_there_is_one_and_says_when_there_is_not(lab: Lab) -> None:
    raw = ready(lab)
    base = datetime.now(UTC).replace(minute=30, second=0, microsecond=0)
    push(lab, raw, [ev("noisy")])  # creates the group (and an hourly bucket for the real hour)
    gid = group_id(lab)
    hour = base.replace(minute=0)
    for h in range(1, 9):  # eight prior hours with 2 events each: a baseline of median 2
        sql(lab.e, "INSERT INTO public.event_buckets (group_id, bucket_start, count) VALUES (%s, %s, 2)", gid, hour - timedelta(hours=h))  # fmt: skip
    sql(lab.e, "DELETE FROM public.event_buckets WHERE group_id = %s AND bucket_start = %s", gid, hour)  # fmt: skip
    svc_ingest(lab, [ev("noisy")] * 5, base)  # 5 >= min events but < 3x median(2) = 6
    assert rule_alerts(lab, "error_rate_spike") == []
    svc_ingest(lab, [ev("noisy")], base)  # 6 >= 3 x 2
    (spike,) = rule_alerts(lab, "error_rate_spike")
    assert spike["measured"]["baseline_available"] is True and spike["measured"]["median_previous_hours"] == 2  # fmt: skip
    assert spike["severity"] == "medium" and spike["group_id"] == gid
    # a brand-new group has no baseline: the absolute threshold applies and the alert says so
    svc_ingest(lab, [ev("brand new")] * 5, base)
    spikes = rule_alerts(lab, "error_rate_spike")
    fresh = next(s for s in spikes if s["group_id"] != gid)
    assert fresh["measured"]["baseline_available"] is False and fresh["measured"]["median_previous_hours"] is None  # fmt: skip


def test_silence_after_activity_raises_a_gap_alert_that_clears_when_events_resume(lab: Lab) -> None:
    raw = ready(lab)
    svc_ingest(lab, [ev("early")], datetime.now(UTC) - timedelta(hours=8))
    (gap,) = rule_alerts(lab, "telemetry_gap")  # evaluated lazily when alerts are read
    assert gap["severity"] == "info" and gap["measured"]["silence_hours"] == 6
    assert len(rule_alerts(lab, "telemetry_gap")) == 1  # idempotent
    status = lab.s.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").json()
    assert status["has_events"] is True
    push(lab, raw, [ev("back again")])
    (closed,) = [a for a in alerts_of(lab) if a["rule"] == "telemetry_gap"]
    assert closed["status"] == "resolved"
    hist = lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts/{closed['id']}").json()["history"]
    assert hist[-1]["action"] == "resolved" and hist[-1]["actor_user_id"] is None


def test_no_gap_alert_for_a_project_that_never_sent_events_or_has_ingestion_off(lab: Lab) -> None:
    assert alerts_of(lab) == []
    enable(lab)
    assert (
        alerts_of(lab) == []
    )  # never active: silence is disclosed in telemetry-status, not alerted
    status = lab.s.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").json()
    assert status["has_events"] is False and status["summary"] == "No application events have been received."  # fmt: skip


def test_open_alerts_are_capped_and_the_overflow_is_counted(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, alert_open_cap=1)
    push(lab, raw, [ev("first", level="fatal")])
    push(lab, raw, [ev("second", level="fatal")])
    push(lab, raw, [ev("third", level="fatal")])
    by_rule = {a["rule"]: a for a in alerts_of(lab)}
    assert set(by_rule) == {"new_error_group", "alert_overflow"}
    assert by_rule["alert_overflow"]["occurrences"] == 2 and by_rule["alert_overflow"]["measured"]["cap"] == 1  # fmt: skip


def test_a_rule_failure_never_loses_accepted_events(lab: Lab, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    raw = ready(lab)

    def boom(*a: Any, **k: Any) -> None:
        raise RuntimeError("rule bug")

    monkeypatch.setattr(alerts, "evaluate_groups", boom)
    assert push(lab, raw, [ev("kept")]).json()["accepted"] == 1
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(1,)]
    status = lab.s.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").json()
    assert status["evaluation_errors_last_24h"] == 1  # disclosed, not hidden


# ---- correlation ------------------------------------------------------------------------------


def test_correlation_links_only_verified_same_project_identifiers(lab: Lab) -> None:
    raw = ready(lab)
    run_id, result_id = lab.w.run()
    other = World(lab.e)
    foreign_run, foreign_result = other.run()
    foreign_finding = uuid.uuid4()
    push(lab, raw, [ev("linked", run_id=str(run_id), result_id=str(result_id)),
                    ev("foreign", run_id=str(foreign_run), result_id=str(foreign_result),
                       finding_id=str(foreign_finding))])  # fmt: skip
    rows = {r[0]: json.loads(r[1]) for r in sql(lab.e, "SELECT message, correlation::text FROM public.events")}  # fmt: skip
    assert rows["linked"] == {"run_id": str(run_id), "result_id": str(result_id)}
    assert rows["foreign"] == {"unverified": ["run_id", "result_id", "finding_id"]}
    claimed = json.loads(sql(lab.e, "SELECT claimed::text FROM public.events WHERE message = 'foreign'")[0][0])  # fmt: skip
    assert claimed["run_id"] == str(foreign_run)  # the claim is kept as a claim, never a link
    detail = lab.s.request("GET", f"{API}/projects/{lab.pid}/event-groups").json()["items"]
    assert len(detail) == 2


def test_overlap_with_a_run_window_is_labelled_proximity_not_cause(lab: Lab) -> None:
    raw = ready(lab)
    run_id, _ = lab.w.run()
    started = sql(lab.e, "SELECT started_at FROM public.test_runs WHERE id = %s", run_id)[0][0]
    push(lab, raw, [ev("outside")])  # now is after the run finished
    svc_ingest(lab, [ev("during")], started)  # inside the run's start..finish window
    svc_ingest(lab, [ev("prod event", environment="production")], started)
    rows = {r[0]: json.loads(r[1]) for r in sql(lab.e, "SELECT message, correlation::text FROM public.events")}  # fmt: skip
    assert rows["during"] == {"during_run": str(run_id)}
    assert rows["outside"] == {}
    assert rows["prod event"] == {}  # only local/development/staging events are matched by time
    assert "run_id" not in rows["during"]  # never rendered as a verified link


# ---- alert lifecycle, authorization and audit -----------------------------------------------------


def test_alert_actions_follow_project_access_and_are_audited(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("denied", level="fatal")])
    (a,) = alerts_of(lab)
    url = f"{API}/projects/{lab.pid}/alerts/{a['id']}"
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    runner, rn = user(lab.e)
    add_member(lab.s, lab.pid, runner, "run")
    _, stranger = user(lab.e)
    assert rd.request("GET", url).status_code == 200  # read access can see
    assert rd.request("POST", f"{url}/acknowledge", json={}).status_code == 403
    assert rd.request("POST", f"{url}/resolve", json={}).status_code == 403
    assert stranger.request("GET", url).status_code == 404
    assert stranger.request("GET", f"{API}/projects/{lab.pid}/alerts").status_code == 404
    other = World(lab.e)
    assert other.s.request("GET", f"{API}/projects/{other.pid}/alerts/{a['id']}").status_code == 404
    assert other.s.request("POST", f"{API}/projects/{other.pid}/alerts/{a['id']}/acknowledge", json={}).status_code == 404  # fmt: skip
    assert rn.request("POST", f"{url}/acknowledge", json={"note": "  looking   now "}).json()["status"] == "acknowledged"  # fmt: skip
    assert rn.request("POST", f"{url}/acknowledge", json={}).status_code == 409
    assert rn.request("POST", f"{url}/acknowledge", json={"note": "x" * 1001}).status_code == 422
    assert rn.request("POST", f"{url}/resolve", json={}).json()["status"] == "resolved"
    assert rn.request("POST", f"{url}/resolve", json={}).status_code == 409
    hist = lab.s.request("GET", url).json()["history"]
    assert [h["action"] for h in hist] == ["created", "acknowledged", "resolved"]
    assert hist[1]["note"] == "looking now" and hist[1]["actor_user_id"] == runner["id"]
    assert [r[0] for r in lab.e.audit("alert.acknowledge")] == ["success"]
    assert [r[0] for r in lab.e.audit("alert.resolve")] == ["success"]
    assert lab.s.request("GET", f"{url}?x=1").status_code == 200
    assert lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts", params={"status": "nope"}).status_code == 422  # fmt: skip
    assert lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts", params={"status": "resolved"}).json()["items"][0]["id"] == a["id"]  # fmt: skip
    assert alerts_of(lab, severity="low") == [] and len(alerts_of(lab, rule="new_error_group")) == 1


def test_the_audit_trail_has_no_event_content_or_keys(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("customer 4711 card 4111111111111111 exploded", level="fatal")])
    blob = json.dumps(sql(lab.e, "SELECT detail::text FROM public.audit_events"))
    assert "4111111111111111" not in blob and raw not in blob


def test_break_glass_grants_read_alerts_but_never_change_them(lab: Lab) -> None:
    from test_plans_api import grant_bg

    raw = ready(lab)
    push(lab, raw, [ev("seen by break glass", level="fatal")])
    (a,) = alerts_of(lab)
    sup, sa = user(lab.e, "super_admin")
    assert grant_bg(sa, lab.pid).status_code == 201
    url = f"{API}/projects/{lab.pid}/alerts/{a['id']}"
    assert sa.request("GET", url).status_code == 200
    assert sa.request("POST", f"{url}/acknowledge", json={}).status_code == 403
    assert new_key(lab, session=sa).status_code == 403


# ---- telemetry disclosure ---------------------------------------------------------------------------


def test_telemetry_status_states_what_was_and_was_not_received(lab: Lab) -> None:
    status = lambda: lab.s.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").json()  # noqa: E731
    empty = status()
    assert empty["has_events"] is False and empty["ingest_enabled"] is False and empty["active_keys"] == 0  # fmt: skip
    assert empty["last_event_at"] is None and len(empty["limits"]) >= 3
    raw = ready(lab)
    push(lab, raw, [ev("with stack", error_type="E", stack='File "a.py", line 1, in f'),
                    ev("without", level="warning"), ev("bad"), {"x": 1}])  # fmt: skip
    now = status()
    assert now["has_events"] is True and now["ingest_enabled"] is True and now["active_keys"] == 1
    assert now["events_last_24h_by_level"] == {"error": 2, "warning": 1}
    assert now["events_last_24h_by_environment"] == {"staging": 3}
    assert now["dropped_last_24h"] == {"invalid_schema": 1}
    assert now["share_of_groups_with_stack"] == 0.33 and now["samples_with_verified_link"] == 0
    assert any("trace" in x.lower() for x in now["limits"])
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    assert rd.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").status_code == 200
    _, stranger = user(lab.e)
    assert stranger.request("GET", f"{API}/projects/{lab.pid}/telemetry-status").status_code == 404


# ---- internal sources -----------------------------------------------------------------------------------


def test_failed_runs_and_reopened_findings_raise_internal_alerts(lab: Lab) -> None:
    run_id, result_id = lab.failed_result([("test_a", "AssertionError")])
    with factory(lab.e)() as db:
        alerts.evaluate_run(db, None, uuid.UUID(run_id))
        alerts.evaluate_run(db, None, uuid.UUID(run_id))  # idempotent
        db.commit()
    (a,) = rule_alerts(lab, "run_failed")
    assert (a["source"], a["severity"], a["run_id"], a["result_id"]) == ("internal", "medium", run_id, result_id)  # fmt: skip
    assert a["evidence"]["result_ids"] == [result_id] and a["occurrences"] == 2
    # a completed run without failed results raises nothing
    ok_run, _ = lab.w.run()
    with factory(lab.e)() as db:
        alerts.evaluate_run(db, None, ok_run)
        db.commit()
    assert len(rule_alerts(lab, "run_failed")) == 1

    fid, _, _ = lab.finding()
    sql(lab.e, "UPDATE public.findings SET status = 'fixed' WHERE id = %s", fid)
    lab.w.ingest(scan(fr(n=0)))  # the scanner reports it again: reopened
    (f,) = rule_alerts(lab, "finding_reopened")
    assert (f["source"], f["severity"], f["finding_id"]) == ("internal", "high", fid)
    assert sql(lab.e, "SELECT status FROM public.findings WHERE id = %s", fid) == [("reopened",)]


def test_alerting_never_changes_findings_runs_or_verification(lab: Lab) -> None:
    fid, _, _ = lab.finding(status="triaged", state="unverified")
    before = sql(lab.e, "SELECT status, verification_state, severity FROM public.findings WHERE id = %s", fid)  # fmt: skip
    raw = ready(lab)
    push(lab, raw, [ev("claims fix", level="fatal", finding_id=fid)] * 3)
    assert sql(lab.e, "SELECT status, verification_state, severity FROM public.findings WHERE id = %s", fid) == before  # fmt: skip
    assert sql(lab.e, "SELECT count(*) FROM public.verification_attempts") == [(0,)]


# ---- rate limits -----------------------------------------------------------------------------------------


def test_per_key_rate_limits_and_failed_auth_throttle(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, ingest_requests_per_minute=2, ingest_events_per_minute=5, ingest_failed_auth_per_minute=3)  # fmt: skip
    assert push(lab, raw, [ev()]).status_code == 202 and push(lab, raw, [ev()]).status_code == 202
    limited = push(lab, raw, [ev()])
    assert limited.status_code == 429 and limited.headers["retry-after"] == "60"
    assert limited.json()["error"]["code"] == "rate_limited"
    tweak(lab, ingest_requests_per_minute=50, ingest_events_per_minute=5, ingest_failed_auth_per_minute=3)  # fmt: skip
    assert push(lab, raw, [ev()] * 6).status_code == 429  # 6 events > 5 per minute, none stored
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(2,)]
    drops = sql(lab.e, "SELECT dropped::text FROM public.ingest_stats WHERE project_id = %s", lab.pid)  # fmt: skip
    assert json.loads(drops[0][0]).get("rate_limited", 0) >= 1  # disclosed in telemetry
    codes = [push(lab, "sai_ing_000000000000_" + "z" * 43, [ev()]).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]  # then refused before any key lookup


# ---- failure-to-test loop --------------------------------------------------------------------------------------


STACK = 'Traceback (most recent call last):\n  File "/app/pay.py", line 9, in charge\n    total / 0\nZeroDivisionError: division by zero'  # fmt: skip


def group_alert(lab: Lab, raw: str, *, stack: str | None = STACK, n: int = 3, **over: Any) -> dict:
    push(lab, raw, [ev("charge failed password=hunter2hunter2", error_type="ZeroDivisionError", stack=stack, **over)] * n)  # fmt: skip
    return next(a for a in alerts_of(lab) if a["rule"] == "new_error_group")


def test_investigation_of_an_alert_uses_redacted_evidence_and_never_claims_a_cause(lab: Lab) -> None:  # fmt: skip
    raw = ready(lab)
    a = group_alert(lab, raw)
    gid, sample = a["group_id"], sql(lab.e, "SELECT id FROM public.events LIMIT 1")[0][0]
    lab.provider.push({"causes": [
        {"label": "likely", "statement": "A divisor is zero in charge().",
         "evidence_ids": [f"group:{short(gid)}", f"event:{short(str(sample))}"],
         "reproduction_steps": ["Call charge() with an empty cart"]},
        {"label": "hypothesis", "statement": "Made up", "evidence_ids": ["event:deadbeef"],
         "reproduction_steps": []},
    ]})  # fmt: skip
    run = lab.ok({"workflow": "investigation", "alert_id": a["id"]})
    assert (run["status"], run["used_llm"], run["result"]["classification"]) == ("succeeded", True, "reported_error")  # fmt: skip
    assert [c["label"] for c in run["result"]["causes"]] == ["likely"]  # the uncited one is dropped
    assert run["result"]["dropped"] == 1 and "nothing was re-run" in run["result"]["limitations"].lower()  # fmt: skip
    prompt = lab.provider.calls[0].request.prompt
    assert "ZeroDivisionError" in prompt and "hunter2hunter2" not in prompt  # redacted twice over
    assert "<<<EVIDENCE" in prompt  # shown only inside the untrusted-data delimiters
    detail = lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts/{a['id']}").json()
    assert detail["cause_status"] == "investigated" and detail["agent_run_id"] == run["id"]
    assert [h["action"] for h in detail["history"]][-1] == "investigated"
    assert lab.e.audit("alert.investigate")


def test_nothing_calls_a_model_because_an_alert_fired(lab: Lab) -> None:
    raw = ready(lab)
    group_alert(lab, raw)
    assert lab.provider.calls == [] and sql(lab.e, "SELECT count(*) FROM public.llm_usage") == [
        (0,)
    ]
    assert sql(lab.e, "SELECT count(*) FROM public.agent_runs") == [(0,)]


def test_a_measurement_alert_is_explained_not_sent_to_a_model(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, event_daily_quota=1)
    push(lab, raw, [ev("a"), ev("b")])
    (drop,) = rule_alerts(lab, "ingest_dropping")
    run = lab.ok({"workflow": "investigation", "alert_id": drop["id"]})
    assert run["result"]["classification"] == "no_failure_evidence" and run["used_llm"] is False
    assert lab.provider.calls == []
    reg = lab.ok({"workflow": "regression", "alert_id": drop["id"]})
    assert reg["result"]["eligible"] is False and lab.provider.calls == []


def test_alert_subjects_are_project_scoped_and_exclusive(lab: Lab) -> None:
    raw = ready(lab)
    a = group_alert(lab, raw)
    other = World(lab.e)
    r = lab.run({"workflow": "investigation", "alert_id": a["id"]}, other.s, other.pid)
    assert r.status_code == 404
    r = lab.run({"workflow": "regression", "alert_id": str(uuid.uuid4())})
    assert r.status_code == 404
    both = lab.run(
        {"workflow": "investigation", "alert_id": a["id"], "finding_id": str(uuid.uuid4())}
    )
    assert both.status_code == 422
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    assert lab.run({"workflow": "investigation", "alert_id": a["id"]}, rd).status_code == 403
    assert lab.provider.calls == []


def set_framework(lab: Lab) -> None:
    sql(lab.e, "UPDATE public.analysis_snapshots SET detected = %s::jsonb WHERE project_id = %s",
        json.dumps({"facts": {"test_tools": [{"name": "pytest"}]}}), lab.pid)  # fmt: skip


def test_a_regression_draft_needs_enough_evidence_and_says_what_is_missing(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("charge failed", error_type="ZeroDivisionError")] * 3)  # no stack trace
    (alert,) = [x for x in alerts_of(lab) if x["rule"] == "new_error_group"]
    run = lab.ok({"workflow": "regression", "alert_id": alert["id"]})
    reason = run["result"]["reason"]
    assert run["result"]["eligible"] is False
    assert "No stack trace was reported" in reason
    assert "No analysed source with a supported test framework" in reason
    assert lab.provider.calls == [] and sql(lab.e, "SELECT count(*) FROM public.regression_tests") == [(0,)]  # fmt: skip


def test_an_evidenced_alert_yields_a_linked_text_only_proposal_and_nothing_runs(lab: Lab) -> None:
    raw = ready(lab)
    set_framework(lab)
    a = group_alert(lab, raw)
    runs_before = sql(lab.e, "SELECT count(*) FROM public.test_runs WHERE project_id = %s", lab.pid)
    lab.provider.push(draft([f"group:{short(a['group_id'])}"]))
    run = lab.ok({"workflow": "regression", "alert_id": a["id"]})
    assert (run["status"], run["used_llm"]) == ("succeeded", True)
    pid = run["result"]["proposal_id"]
    row = sql(lab.e, "SELECT status, alert_id::text, event_group_id::text, finding_id, project_id::text FROM public.regression_tests WHERE id = %s", pid)[0]  # fmt: skip
    assert row == ("proposed", a["id"], a["group_id"], None, lab.pid)
    got = lab.s.request("GET", f"{API}/projects/{lab.pid}/regression-proposals/{pid}").json()
    assert got["alert_id"] == a["id"] and got["event_group_id"] == a["group_id"]
    detail = lab.s.request("GET", f"{API}/projects/{lab.pid}/alerts/{a['id']}").json()
    assert detail["proposal_ids"] == [pid]
    assert sql(lab.e, "SELECT count(*) FROM public.test_runs WHERE project_id = %s", lab.pid) == runs_before  # fmt: skip
    assert lab.e.audit("alert.regression_draft")
    # accepting records a decision only
    done = lab.s.request("POST", f"{API}/projects/{lab.pid}/regression-proposals/{pid}/decision", json={"decision": "accepted"})  # fmt: skip
    assert done.status_code == 200 and done.json()["status"] == "accepted"
    assert sql(lab.e, "SELECT count(*) FROM public.test_runs WHERE project_id = %s", lab.pid) == runs_before  # fmt: skip
    # the stored draft cannot be rewritten or re-pointed
    with pytest.raises(Exception, match="cannot be edited"):
        sql(lab.e, "UPDATE public.regression_tests SET alert_id = NULL WHERE id = %s", pid)


def test_the_regression_draft_must_cite_the_evidence_it_was_shown(lab: Lab) -> None:
    raw = ready(lab)
    set_framework(lab)
    a = group_alert(lab, raw)
    lab.provider.push(draft(["event:deadbeef"]))
    lab.provider.push(draft(["event:deadbeef"]))
    run = lab.ok({"workflow": "regression", "alert_id": a["id"]})
    assert run["status"] == "degraded" and run["degraded_reason"] == "invalid_output"
    assert sql(lab.e, "SELECT count(*) FROM public.regression_tests") == [(0,)]


def test_without_a_model_an_alert_investigation_degrades_and_keeps_the_explanation(lab: Lab) -> None:  # fmt: skip
    raw = ready(lab)
    a = group_alert(lab, raw)
    lab.install(provider=None)
    run = lab.ok({"workflow": "investigation", "alert_id": a["id"]})
    assert (run["status"], run["degraded_reason"]) == ("degraded", "llm_disabled")
    assert run["result"]["classification"] == "reported_error" and run["result"]["causes"] == []


# ---- retention ---------------------------------------------------------------------------------------------------


def age_everything(lab: Lab, days: int) -> None:
    sql(lab.e, "UPDATE public.events SET received_at = received_at - %s * interval '1 day'", days)
    sql(lab.e, "UPDATE public.event_buckets SET bucket_start = bucket_start - %s * interval '1 day'", days)  # fmt: skip
    sql(lab.e, "UPDATE public.event_groups SET first_seen = first_seen - %s * interval '1 day', last_seen = last_seen - %s * interval '1 day'", days, days)  # fmt: skip


def test_retention_purges_expired_data_and_keeps_what_is_still_needed(lab: Lab) -> None:
    raw = ready(lab)
    push(lab, raw, [ev("old open", level="fatal")])  # its alert stays open
    push(lab, raw, [ev("old resolved", level="fatal")])
    done_alert = next(a for a in alerts_of(lab) if a["group_id"] == sql(lab.e, "SELECT id::text FROM public.event_groups WHERE message_norm = 'old resolved'")[0][0])  # fmt: skip
    lab.s.request("POST", f"{API}/projects/{lab.pid}/alerts/{done_alert['id']}/resolve", json={})
    age_everything(lab, 400)
    sql(lab.e, "UPDATE public.alerts SET closed_at = now() - interval '400 days' WHERE status = 'resolved'")  # fmt: skip
    push(lab, raw, [ev("fresh")])
    settings = lab.e.app.state.settings
    dry = event_retention.purge(factory(lab.e), settings, dry_run=True)
    assert dry["events"] == 2 and dry["alerts"] == 1
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(3,)]  # a dry run deletes nothing
    done = event_retention.purge(factory(lab.e), settings, dry_run=False)
    # alerts go first, so the resolved alert's quiet group goes in the same pass; the open
    # alert's group stays
    assert done["events"] == 2 and done["alerts"] == 1 and done["event_groups"] == 1
    again = event_retention.purge(factory(lab.e), settings, dry_run=False)
    assert again["event_groups"] == 0 and again["alerts"] == 0
    left = {r[0] for r in sql(lab.e, "SELECT message_norm FROM public.event_groups")}
    assert left == {"old open", "fresh"}
    assert [a["title"] for a in alerts_of(lab)] != [] and len(alerts_of(lab)) == 1


def test_groups_and_alerts_behind_a_proposal_are_kept(lab: Lab) -> None:
    raw = ready(lab)
    set_framework(lab)
    a = group_alert(lab, raw)
    lab.provider.push(draft([f"group:{short(a['group_id'])}"]))
    lab.ok({"workflow": "regression", "alert_id": a["id"]})
    lab.s.request("POST", f"{API}/projects/{lab.pid}/alerts/{a['id']}/resolve", json={})
    age_everything(lab, 400)
    sql(lab.e, "UPDATE public.alerts SET closed_at = now() - interval '400 days' WHERE status = 'resolved'")  # fmt: skip
    event_retention.purge(factory(lab.e), lab.e.app.state.settings, dry_run=False)
    assert sql(lab.e, "SELECT count(*) FROM public.event_groups") == [(1,)]
    assert sql(lab.e, "SELECT count(*) FROM public.alerts") == [(1,)]
    assert sql(lab.e, "SELECT count(*) FROM public.regression_tests") == [(1,)]


# ---- helpers used by the file ------------------------------------------------------------------------------------


def test_route_inventory_matches_the_design(lab: Lab) -> None:
    paths = {(m.upper(), p) for p, ops in lab.e.app.openapi()["paths"].items() for m in ops}
    for want in (("POST", "/api/v1/ingest/events"), ("POST", "/api/v1/projects/{project_id}/ingest-keys"),
                 ("GET", "/api/v1/projects/{project_id}/alerts"),
                 ("POST", "/api/v1/projects/{project_id}/alerts/{alert_id}/acknowledge"),
                 ("GET", "/api/v1/projects/{project_id}/telemetry-status")):  # fmt: skip
        assert want in paths
    assert not any("alerts" in p and m in ("PUT", "PATCH", "DELETE") for m, p in paths)  # no edits
