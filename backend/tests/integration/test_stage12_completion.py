"""Stage 12 completion (ADR-0011 amendments): event de-duplication, organization bounds, proxy
and throttling behaviour, OTLP ingestion, trace correlation, model usage and the cost and
resource alert rules. Disposable database, fake provider, no network."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_agent_workflows import Lab, lab, sql  # noqa: F401 (lab is a fixture)
from test_observability import (
    alerts_of,
    ev,
    factory,
    key,
    policy,
    push,
    ready,
    rule_alerts,
    tweak,
)
from test_plans_api import API, add_member, user
from test_runs_jobs import make_env  # noqa: F401 (a fixture)

from sentinel_ai.services import alerts, event_retention

OTLP = f"{API}/ingest/otlp/v1/logs"


def telemetry(lab: Lab) -> dict:
    r = lab.s.request("GET", f"{API}/projects/{lab.pid}/telemetry-status")
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


# ---- de-duplication ---------------------------------------------------------------------------


def test_a_retried_event_is_counted_once(lab: Lab) -> None:
    raw = ready(lab)
    eid = str(uuid.uuid4())
    first = push(lab, raw, [ev("once", event_id=eid)])
    again = push(lab, raw, [ev("once", event_id=eid)])
    assert first.json() == {"accepted": 1, "dropped": {}}
    assert again.json() == {"accepted": 0, "dropped": {"duplicate": 1}}
    assert sql(lab.e, "SELECT total_count FROM public.event_groups") == [(1,)]
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(1,)]
    twice = push(lab, raw, [ev("dup", event_id=eid), ev("dup2", event_id=str(uuid.uuid4()))])
    assert twice.json() == {"accepted": 1, "dropped": {"duplicate": 1}}  # duplicate of the first id


def test_the_same_id_twice_in_one_batch_and_without_ids(lab: Lab) -> None:
    raw = ready(lab)
    eid = str(uuid.uuid4())
    r = push(lab, raw, [ev("same", event_id=eid)] * 3)
    assert r.json() == {"accepted": 1, "dropped": {"duplicate": 2}}
    r = push(lab, raw, [ev("no id")] * 3)  # no id means no de-duplication, as documented
    assert r.json() == {"accepted": 3, "dropped": {}}


def test_duplicates_do_not_use_the_daily_quota_and_ids_are_per_project(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, event_daily_quota=2)
    eid = str(uuid.uuid4())
    assert push(lab, raw, [ev("a", event_id=eid)]).json()["accepted"] == 1
    r = push(lab, raw, [ev("a", event_id=eid), ev("b")])
    assert r.json() == {"accepted": 1, "dropped": {"duplicate": 1}}  # the duplicate cost nothing
    from test_findings import World

    other = World(lab.e)
    other.s.request("PUT", f"{API}/projects/{other.pid}/policies/observability_ingest", json={"value": {"enabled": True}})  # fmt: skip
    k2 = other.s.request("POST", f"{API}/projects/{other.pid}/ingest-keys", json={"label": "x"}).json()["key"]  # fmt: skip
    assert push(lab, k2, [ev("a", event_id=eid)]).json()["accepted"] == 1  # same id, other project


def test_an_event_id_can_be_reused_after_24_hours_and_old_ids_are_purged(lab: Lab) -> None:
    raw = ready(lab)
    eid = str(uuid.uuid4())
    push(lab, raw, [ev("x", event_id=eid)])
    sql(lab.e, "UPDATE public.ingest_event_ids SET received_at = now() - interval '25 hours'")
    assert push(lab, raw, [ev("x", event_id=eid)]).json()["accepted"] == 1
    assert sql(lab.e, "SELECT count(*) FROM public.ingest_event_ids") == [(1,)]
    sql(lab.e, "UPDATE public.ingest_event_ids SET received_at = now() - interval '3 days'")
    done = event_retention.purge(factory(lab.e), lab.e.app.state.settings, dry_run=False)
    assert done["ingest_event_ids"] == 1


# ---- organization bounds -----------------------------------------------------------------------


def org_put(lab: Lab, session: Any, value: Any) -> Any:
    return session.request(
        "PUT", f"{API}/admin/policies/alert_threshold_bounds", json={"value": value}
    )


def test_the_organization_narrows_what_projects_may_set(lab: Lab) -> None:
    _, sup = user(lab.e, "super_admin")
    dev, ds = user(lab.e)
    narrowed = {"new_group_events": {"min": 2, "max": 10}}
    assert org_put(lab, ds, narrowed).status_code == 403  # developers cannot
    assert (
        org_put(lab, sup, {"new_group_events": {"min": 0, "max": 10}}).status_code == 422
    )  # wider than built in
    assert org_put(lab, sup, {"new_group_events": {"min": 9, "max": 3}}).status_code == 422
    assert org_put(lab, sup, {"made_up": {"min": 1, "max": 3}}).status_code == 422
    assert org_put(lab, sup, narrowed).status_code == 200
    assert (
        policy(lab, "alert_thresholds", {"new_group_events": 1}).status_code == 422
    )  # below the org minimum
    assert policy(lab, "alert_thresholds", {"new_group_events": 11}).status_code == 422
    assert policy(lab, "alert_thresholds", {"new_group_events": 4}).status_code == 200
    assert telemetry(lab)["thresholds"]["new_group_events"] == 4
    assert telemetry(lab)["threshold_bounds"]["new_group_events"] == [2, 10]
    # the project key itself is not a global key
    assert lab.s.request("PUT", f"{API}/projects/{lab.pid}/policies/alert_threshold_bounds", json={"value": narrowed}).status_code == 422  # fmt: skip
    assert lab.e.audit("policy.update")  # audited like every policy change
    assert dev


def test_narrowing_later_takes_effect_on_existing_project_values(lab: Lab) -> None:
    _, sup = user(lab.e, "super_admin")
    assert policy(lab, "alert_thresholds", {"new_group_events": 1}).status_code == 200
    assert telemetry(lab)["thresholds"]["new_group_events"] == 1
    assert org_put(lab, sup, {"new_group_events": {"min": 5, "max": 20}}).status_code == 200
    assert telemetry(lab)["thresholds"]["new_group_events"] == 5  # clamped when read
    raw = ready(lab)
    push(lab, raw, [ev("x")] * 4)
    assert rule_alerts(lab, "new_error_group") == []  # 4 < 5: the organization's floor applies
    push(lab, raw, [ev("x")])
    assert len(rule_alerts(lab, "new_error_group")) == 1


# ---- proxy and failed-key throttling ---------------------------------------------------------------


def post_as(lab: Lab, peer: str, raw: str | None, headers: dict | None = None) -> Any:
    h = {"Authorization": f"Bearer {raw}"} if raw else {}
    return TestClient(lab.e.app, client=(peer, 5000)).post(
        f"{API}/ingest/events", json={"events": [ev()]}, headers={**h, **(headers or {})}
    )


BAD = "sai_ing_000000000000_" + "z" * 43


def test_a_sender_that_authenticated_keeps_working_while_its_address_is_throttled(lab: Lab) -> None:
    raw = ready(lab)
    new_key = key(lab)  # valid, but never used from this process yet
    tweak(lab, ingest_failed_auth_per_minute=3)
    assert post_as(lab, "203.0.113.5", raw).status_code == 202  # known now
    assert [post_as(lab, "203.0.113.5", BAD).status_code for _ in range(5)] == [
        401,
        401,
        401,
        429,
        429,
    ]
    assert post_as(lab, "203.0.113.5", raw).status_code == 202  # the known key is still served
    assert (
        post_as(lab, "203.0.113.5", new_key).status_code == 429
    )  # an unseen key waits out the minute
    assert (
        post_as(lab, "203.0.113.99", new_key).status_code == 202
    )  # other addresses are unaffected


def test_a_known_key_is_still_fully_authenticated_while_throttled(lab: Lab) -> None:
    raw = ready(lab)
    tweak(lab, ingest_failed_auth_per_minute=2)
    assert post_as(lab, "203.0.113.5", raw).status_code == 202
    for _ in range(3):
        post_as(lab, "203.0.113.5", BAD)
    revoked = lab.s.request("GET", f"{API}/projects/{lab.pid}/ingest-keys").json()["items"][0]["id"]
    lab.s.request("DELETE", f"{API}/projects/{lab.pid}/ingest-keys/{revoked}")
    assert post_as(lab, "203.0.113.5", raw).status_code == 401  # remembered, but revoked: refused


def test_behind_a_trusted_proxy_each_client_has_its_own_failure_budget(lab: Lab) -> None:
    ready(lab)
    tweak(lab, ingest_failed_auth_per_minute=2, trusted_proxy_cidrs=["10.0.0.0/8"])
    via = lambda xff: post_as(lab, "10.1.1.1", BAD, {"X-Forwarded-For": xff}).status_code  # noqa: E731
    assert [via("198.51.100.1") for _ in range(3)] == [401, 401, 429]
    assert via("198.51.100.2") == 401  # a different client behind the same proxy is not blocked
    # a peer that is not a trusted proxy cannot choose its identity with the header
    spoof = lambda xff: post_as(lab, "203.0.113.8", BAD, {"X-Forwarded-For": xff}).status_code  # noqa: E731
    assert [spoof("1.1.1.1"), spoof("2.2.2.2"), spoof("3.3.3.3")] == [401, 401, 429]


def test_without_trusted_proxies_all_clients_behind_one_address_share_a_budget(lab: Lab) -> None:
    ready(lab)
    tweak(lab, ingest_failed_auth_per_minute=2)
    codes = [post_as(lab, "10.1.1.1", BAD, {"X-Forwarded-For": f"198.51.100.{i}"}).status_code for i in range(4)]  # fmt: skip
    assert codes == [401, 401, 429, 429]  # the default is unchanged: the header is not trusted


def test_the_audit_log_uses_the_forwarded_client_only_for_a_trusted_proxy(lab: Lab) -> None:
    dev = lab.e.make_user()
    tweak(lab, trusted_proxy_cidrs=["10.0.0.0/8"], session_cookie_secure=False)

    def login(peer: str, xff: str) -> None:
        c = TestClient(lab.e.app, client=(peer, 1), headers={"Origin": "http://localhost:5173"})
        c.post(f"{API}/auth/login", json={"email": dev["email"], "password": "wrong-password-123"},
               headers={"X-Forwarded-For": xff})  # fmt: skip

    login("10.2.2.2", "198.51.100.77")
    login("203.0.113.50", "1.2.3.4")  # untrusted peer: the header is ignored
    ips = {str(r[0]) for r in sql(lab.e, "SELECT ip_address FROM public.audit_events WHERE action = 'auth.login' AND ip_address IS NOT NULL")}  # fmt: skip
    assert ips == {"198.51.100.77", "203.0.113.50"}


# ---- OTLP ingestion ------------------------------------------------------------------------------------


def otlp_doc(*records: dict, service: str = "checkout") -> dict:
    return {"resourceLogs": [{"resource": {"attributes": [
        {"key": "service.name", "value": {"stringValue": service}},
        {"key": "deployment.environment", "value": {"stringValue": "staging"}}]},
        "scopeLogs": [{"scope": {"name": "app"}, "logRecords": list(records)}]}]}  # fmt: skip


def otlp_rec(body: str = "boom", sev: int = 17, **over: Any) -> dict:
    return {"timeUnixNano": str(int(datetime.now(UTC).timestamp() * 1e9)), "severityNumber": sev,
            "body": {"stringValue": body}, **over}  # fmt: skip


def otlp_post(lab: Lab, raw: str | None, doc: Any, content_type: str = "application/json") -> Any:
    h = {"Authorization": f"Bearer {raw}"} if raw else {}
    return TestClient(lab.e.app).post(OTLP, content=json.dumps(doc), headers={**h, "Content-Type": content_type})  # fmt: skip


def test_otlp_logs_become_the_same_grouped_redacted_events(lab: Lab) -> None:
    raw = ready(lab)
    exc = [{"key": "exception.type", "value": {"stringValue": "ValueError"}},
           {"key": "exception.stacktrace", "value": {"stringValue": 'Traceback\n  File "/a/pay.py", line 4, in charge\nValueError: x'}}]  # fmt: skip
    records = [otlp_rec("charge failed password=hunter2hunter2", attributes=exc)] * 3
    r = otlp_post(lab, raw, otlp_doc(*records))
    assert r.status_code == 200 and r.json() == {}
    g = sql(lab.e, "SELECT service, environment, level_class, error_type, has_stack, total_count FROM public.event_groups")  # fmt: skip
    assert g == [("checkout", "staging", "error", "ValueError", True, 3)]
    stored = " ".join(
        str(x) for row in sql(lab.e, "SELECT message, stack FROM public.events") for x in row
    )
    assert (
        "hunter2hunter2" not in stored and "[REDACTED" in stored
    )  # same redaction as the native path
    assert len(rule_alerts(lab, "new_error_group")) == 1  # and the same alert rules


def test_otlp_severity_floor_and_rejected_records_are_reported(lab: Lab) -> None:
    raw = ready(lab)
    r = otlp_post(
        lab,
        raw,
        otlp_doc(otlp_rec("kept"), otlp_rec("noise", sev=9), otlp_rec("also noise", sev=5)),
    )
    assert r.status_code == 200 and r.json() == {}  # below-floor records are not an error
    assert sql(lab.e, "SELECT sum(accepted) FROM public.ingest_stats")[0][0] == 1
    bad = otlp_post(
        lab, raw, otlp_doc(otlp_rec("fine"), {"severityNumber": 17, "body": {"stringValue": ""}})
    )
    assert bad.json()["partialSuccess"]["rejectedLogRecords"] == 1
    assert "invalid_schema: 1" in bad.json()["partialSuccess"]["errorMessage"]


def test_otlp_uses_the_same_authentication_and_limits(lab: Lab) -> None:
    raw = ready(lab)
    doc = otlp_doc(otlp_rec())
    assert otlp_post(lab, None, doc).status_code == 401
    assert otlp_post(lab, BAD, doc).status_code == 401
    assert otlp_post(lab, raw, doc, "application/x-protobuf").status_code == 415
    assert otlp_post(lab, raw, {"resourceLogs": "nope"}).status_code == 422
    assert otlp_post(lab, raw, {"other": 1}).status_code == 422
    assert otlp_post(lab, raw, otlp_doc(*[otlp_rec()] * 101)).status_code == 422
    assert otlp_post(lab, raw, otlp_doc()).status_code == 422  # nothing to ingest
    assert policy(lab, "observability_ingest", {"enabled": False}).status_code == 200
    r = otlp_post(lab, raw, doc)
    assert (r.status_code, r.json()["error"]["code"]) == (403, "ingest_disabled")
    # a session cookie is not a credential on this route either
    assert lab.s.request("POST", OTLP, content=json.dumps(doc), headers={"Content-Type": "application/json"}).status_code == 401  # fmt: skip


def test_otlp_trace_ids_correlate_with_a_platform_workflow(lab: Lab) -> None:
    raw = ready(lab)
    run_id, _ = lab.w.run()
    trace = lab.s.request("GET", f"{API}/test-runs/{run_id}").json()["trace_id"]
    assert len(trace) == 32 and trace == trace.lower()
    otlp_post(lab, raw, otlp_doc(otlp_rec("under test", traceId=trace, spanId="ab" * 8),
                                 otlp_rec("elsewhere", traceId="cd" * 16)))  # fmt: skip
    rows = {
        r[0]: json.loads(r[1])
        for r in sql(lab.e, "SELECT message, correlation::text FROM public.events")
    }
    assert rows["under test"] == {"trace_run_id": str(run_id)}  # verified: same trace id
    assert "trace_run_id" not in rows["elsewhere"]
    assert (
        telemetry(lab)["samples_with_trace_id"] == 2
        and telemetry(lab)["samples_with_verified_link"] == 1
    )


# ---- trace view ------------------------------------------------------------------------------------------


def test_the_trace_view_joins_workflows_and_reported_events_by_identifier_only(lab: Lab) -> None:
    raw = ready(lab)
    run_id, _ = lab.w.run()
    trace = lab.s.request("GET", f"{API}/test-runs/{run_id}").json()["trace_id"]
    push(
        lab,
        raw,
        [ev("in trace", trace_id=trace), ev("other trace", trace_id="ef" * 16), ev("no trace")],
    )
    r = lab.s.request("GET", f"{API}/projects/{lab.pid}/traces/{trace}")
    assert r.status_code == 200
    body = r.json()
    assert [x["id"] for x in body["runs"]] == [str(run_id)] and body["assistant_runs"] == []
    assert [e["message"] for e in body["events"]] == ["in trace"] and len(body["limits"]) == 2
    # access: another project, a stranger, a bad id and an unknown trace
    from test_findings import World

    other = World(lab.e)
    assert other.s.request("GET", f"{API}/projects/{other.pid}/traces/{trace}").status_code == 404
    _, stranger = user(lab.e)
    assert stranger.request("GET", f"{API}/projects/{lab.pid}/traces/{trace}").status_code == 404
    assert lab.s.request("GET", f"{API}/projects/{lab.pid}/traces/not-a-trace").status_code == 422
    assert lab.s.request("GET", f"{API}/projects/{lab.pid}/traces/{'12' * 16}").status_code == 404
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    assert rd.request("GET", f"{API}/projects/{lab.pid}/traces/{trace}").status_code == 200


def test_assistant_runs_have_trace_ids_that_events_can_share(lab: Lab) -> None:
    raw = ready(lab)
    lab.install(provider=None)
    run = lab.ok({"workflow": "planning", "prompt": "check my dependencies"})
    trace = run["trace_id"]
    assert len(trace) == 32
    push(lab, raw, [ev("from the app", trace_id=trace)])
    view = lab.s.request("GET", f"{API}/projects/{lab.pid}/traces/{trace}").json()
    assert [a["id"] for a in view["assistant_runs"]] == [run["id"]]
    assert view["assistant_runs"][0]["steps"] and view["events"][0]["correlation"] == {"trace_agent_run_id": run["id"]}  # fmt: skip
    assert (
        lab.s.request("GET", f"{API}/projects/{lab.pid}/agent-runs/{run['id']}").json()["trace_id"]
        == trace
    )


# ---- model usage tracking and the cost / resource rules ------------------------------------------------------


def usage(lab: Lab, *, cost: float = 0.1, outcome: str = "ok", at: datetime | None = None, attempts: int = 1,
          run_id: str | None = None, latency: int | None = 200, n: int = 1) -> None:  # fmt: skip
    for _ in range(n):
        sql(lab.e, "INSERT INTO public.llm_usage (project_id, requested_by, purpose, model, input_tokens, output_tokens, estimated_cost_usd, outcome, attempts, latency_ms, agent_run_id, created_at) VALUES (%s, NULL, 'investigation', 'm', 1000, 200, %s, %s, %s, %s, %s, %s)", lab.pid, cost, outcome, attempts, latency, run_id, at or datetime.now(UTC))  # fmt: skip


def test_model_usage_is_tracked_and_labelled_as_estimated_and_incomplete_where_it_is(
    lab: Lab,
) -> None:
    usage(lab, cost=0.1, n=3)
    usage(lab, cost=0.0, outcome="timeout", attempts=3)
    usage(lab, cost=0.0, outcome="blocked_by_budget", attempts=0)
    usage(lab, cost=0.05, outcome="reserved", latency=None)
    usage(lab, cost=0.2, at=datetime.now(UTC) - timedelta(days=3))  # outside the 24 h window
    m = telemetry(lab)["model_usage"]
    assert (m["calls"], m["ok"], m["failed"], m["blocked_by_budget"]) == (6, 3, 1, 1)
    assert m["retries"] == 2 and m["input_tokens"] == 6000 and m["output_tokens"] == 1200
    assert m["estimated_cost_usd"] == pytest.approx(0.35) and m["cost_is_estimate"] is True
    assert m["incomplete_calls"] == 1 and "estimates" in m["note"]
    assert m["average_latency_ms"] > 0 and m["max_latency_ms"] == 200


def test_a_cost_spike_needs_both_the_minimum_and_the_ratio_and_labels_itself_an_estimate(
    lab: Lab,
) -> None:
    usage(lab, cost=0.4)  # below the 0.50 USD minimum: nothing yet
    assert rule_alerts(lab, "llm_cost_spike") == []
    usage(lab, cost=0.7)  # 1.10 USD today, no baseline: the absolute threshold applies
    (spike,) = rule_alerts(lab, "llm_cost_spike")
    assert spike["source"] == "internal" and spike["severity"] == "medium"
    m = spike["measured"]
    assert m["cost_is_estimate"] is True and m["baseline_available"] is False and m["estimated_cost_usd_24h"] == pytest.approx(1.1)  # fmt: skip
    assert "estimate" in spike["next_action"]


def test_a_cost_spike_compares_with_the_median_of_earlier_days_when_there_is_one(lab: Lab) -> None:
    for d in range(2, 7):  # five earlier days at 0.30 USD: a baseline
        usage(lab, cost=0.3, at=datetime.now(UTC) - timedelta(days=d))
    usage(lab, cost=0.6)  # over the minimum, but only 2x the median (the ratio is 3)
    assert rule_alerts(lab, "llm_cost_spike") == []
    usage(lab, cost=0.5)  # 1.10 USD = 3.7x
    (spike,) = rule_alerts(lab, "llm_cost_spike")
    assert spike["measured"]["baseline_available"] is True and spike["measured"]["median_daily_estimated_cost_usd"] == pytest.approx(0.3)  # fmt: skip


def test_cost_thresholds_are_the_projects_to_tune_inside_the_bounds(lab: Lab) -> None:
    usage(lab, cost=1.1)
    assert policy(lab, "alert_thresholds", {"cost_spike_min_usd": 5}).status_code == 200
    assert rule_alerts(lab, "llm_cost_spike") == []  # 1.10 < 5 USD now
    assert policy(lab, "alert_thresholds", {"cost_spike_min_usd": 0}).status_code == 422


def test_runaway_workflows_are_detected_by_count_and_by_retries_in_one_run(lab: Lab) -> None:
    now = datetime.now(UTC)
    for _ in range(19):
        sql(lab.e, "INSERT INTO public.agent_runs (project_id, workflow, status, started_at) VALUES (%s, 'planning', 'running', %s)", lab.pid, now)  # fmt: skip
    assert rule_alerts(lab, "llm_runaway") == []  # 19 < 20 per hour
    sql(lab.e, "INSERT INTO public.agent_runs (project_id, workflow, status, started_at) VALUES (%s, 'planning', 'running', %s)", lab.pid, now)  # fmt: skip
    (a,) = rule_alerts(lab, "llm_runaway")
    assert a["measured"]["assistant_runs_last_hour"] == 20 and a["source"] == "internal"


def test_many_model_attempts_inside_one_run_is_a_runaway_signal(lab: Lab) -> None:
    run = sql(lab.e, "INSERT INTO public.agent_runs (project_id, workflow, status, started_at) VALUES (%s, 'investigation', 'running', now()) RETURNING id", lab.pid)[0][0]  # fmt: skip
    usage(lab, attempts=11, run_id=str(run))
    assert rule_alerts(lab, "llm_runaway") == []
    usage(lab, attempts=1, run_id=str(run))
    assert rule_alerts(lab, "llm_runaway")[0]["measured"]["most_model_attempts_in_one_run"] == 12


def test_a_high_model_failure_rate_is_an_alert_but_budget_blocks_are_not_failures(lab: Lab) -> None:
    usage(lab, n=4, outcome="timeout", cost=0)
    assert rule_alerts(lab, "llm_error_rate") == []  # fewer than 5 settled calls
    usage(lab, n=3, outcome="blocked_by_budget", cost=0, attempts=0)  # blocks are counted apart
    assert rule_alerts(lab, "llm_error_rate") == []
    usage(lab, n=1, outcome="ok")
    (a,) = rule_alerts(lab, "llm_error_rate")
    assert a["measured"]["failure_percent"] == 80.0 and a["measured"]["blocked_by_budget"] == 3


def test_a_healthy_model_history_raises_nothing(lab: Lab) -> None:
    usage(lab, n=10, cost=0.01)
    assert [a for a in alerts_of(lab) if a["source"] == "internal"] == []


def finished_run(lab: Lab, seconds: float, ended_days_ago: float) -> uuid.UUID:
    run_id, _ = lab.w.run()
    end = datetime.now(UTC) - timedelta(days=ended_days_ago)
    sql(lab.e, "UPDATE public.test_runs SET started_at = %s, finished_at = %s WHERE id = %s", end - timedelta(seconds=seconds), end, run_id)  # fmt: skip
    return run_id


def evaluate(lab: Lab, run_id: uuid.UUID) -> None:
    with factory(lab.e)() as db:
        alerts.evaluate_run(db, None, run_id)
        db.commit()


def test_a_run_far_slower_than_its_plan_history_is_an_alert_with_the_comparison(lab: Lab) -> None:
    for d in (4, 3, 2):
        finished_run(lab, 40, d)
    slow = finished_run(lab, 200, 0)
    evaluate(lab, slow)
    (a,) = rule_alerts(lab, "run_duration_anomaly")
    assert (a["source"], a["severity"], a["run_id"]) == ("internal", "low", str(slow))
    m = a["measured"]
    assert m["duration_seconds"] == 200.0 and m["median_previous_seconds"] == 40.0 and m["previous_runs_compared"] == 3  # fmt: skip
    assert a["evidence"]["run_id"] == str(slow) and "verdict" in a["next_action"]


def test_duration_anomalies_need_a_baseline_a_ratio_and_a_minimum_length(lab: Lab) -> None:
    finished_run(lab, 40, 3)
    finished_run(lab, 40, 2)
    short_history = finished_run(lab, 400, 0)
    evaluate(lab, short_history)
    assert rule_alerts(lab, "run_duration_anomaly") == []  # only 2 earlier runs
    finished_run(lab, 40, 1.5)
    slightly = finished_run(lab, 90, 1)  # 2.25x the median: below the ratio of 3
    evaluate(lab, slightly)
    assert rule_alerts(lab, "run_duration_anomaly") == []
    tiny_lab_runs = [finished_run(lab, 5, d) for d in (0.9, 0.8, 0.7)]
    quick = finished_run(lab, 20, 0.1)  # 4x a 5 s median but under the 30 s floor
    evaluate(lab, quick)
    assert rule_alerts(lab, "run_duration_anomaly") == [] and tiny_lab_runs


def test_resource_alerts_follow_the_same_lifecycle_and_access_rules(lab: Lab) -> None:
    usage(lab, cost=1.5)
    (a,) = rule_alerts(lab, "llm_cost_spike")
    url = f"{API}/projects/{lab.pid}/alerts/{a['id']}"
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    assert rd.request("GET", url).status_code == 200
    assert rd.request("POST", f"{url}/acknowledge", json={}).status_code == 403
    assert (
        lab.s.request("POST", f"{url}/acknowledge", json={"note": "known batch job"}).status_code
        == 200
    )
    detail = lab.s.request("GET", url).json()
    assert detail["status"] == "acknowledged" and detail["cause_status"] == "not_investigated"
    # a measurement alert is explained by the investigation workflow, never sent to a model
    run = lab.ok({"workflow": "investigation", "alert_id": a["id"]})
    assert run["result"]["classification"] == "no_failure_evidence" and lab.provider.calls == []


def test_the_limits_endpoint_lists_every_threshold_for_super_admins_only(lab: Lab) -> None:
    _, sup = user(lab.e, "super_admin")
    _, dev = user(lab.e)
    r = sup.request("GET", f"{API}/admin/alert-threshold-limits")
    assert r.status_code == 200
    items = {i["name"]: i for i in r.json()["items"]}
    assert set(items) == set(
        __import__("sentinel_ai.services.observability_policy", fromlist=["x"]).BOUNDS
    )
    assert items["new_group_events"] == {"name": "new_group_events", "default": 3, "min": 1, "max": 100,
                                          "description": items["new_group_events"]["description"]}  # fmt: skip
    assert all(i["description"] for i in items.values())
    assert dev.request("GET", f"{API}/admin/alert-threshold-limits").status_code == 403
    assert lab.s.request("GET", f"{API}/admin/alert-threshold-limits").status_code == 403


def test_the_project_detail_tells_the_caller_their_access_so_the_ui_can_show_the_right_controls(
    lab: Lab,
) -> None:
    """Found in a real browser: GET /projects/{id} returned your_access null, so the UI treated
    every member as read-only and hid the alert, assistant and ingestion controls."""
    from test_plans_api import grant_bg

    url = f"{API}/projects/{lab.pid}"
    assert lab.s.request("GET", url).json()["your_access"] == "manage"  # the owner
    runner, rn = user(lab.e)
    add_member(lab.s, lab.pid, runner, "run")
    reader, rd = user(lab.e)
    add_member(lab.s, lab.pid, reader, "read")
    assert rn.request("GET", url).json()["your_access"] == "run"
    assert rd.request("GET", url).json()["your_access"] == "read"
    _, stranger = user(lab.e)
    assert stranger.request("GET", url).status_code == 404  # no grant, no project
    _, sup = user(lab.e, "super_admin")
    assert grant_bg(sup, lab.pid).status_code == 201
    assert sup.request("GET", url).json()["your_access"] == "read"  # break-glass is read-only
    renamed = lab.s.request("PATCH", url, json={"name": "renamed project"})
    assert renamed.json()["your_access"] == "manage"
