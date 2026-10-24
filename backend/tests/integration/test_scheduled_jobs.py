"""Scheduled alert evaluation and retention (Q125, Q70; ADR-0011). The beat schedule is
configuration; the jobs are the same service functions the CLI runs."""

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from test_agent_workflows import Lab, lab, sql  # noqa: F401 (lab is a fixture)
from test_observability import enable, factory, rule_alerts, svc_ingest
from test_plans_api import user  # noqa: F401
from test_runs_jobs import make_env  # noqa: F401 (a fixture)
from test_stage12_completion import usage

from sentinel_ai.jobs import tasks
from sentinel_ai.jobs.celery_app import EVALUATE_ALERTS, PURGE_EVENTS, make_celery
from sentinel_ai.repositories import observability as repo
from sentinel_ai.services import alerts
from support import make_settings


def ev(message: str = "boom") -> dict:
    return {"level": "error", "service": "api", "environment": "staging", "message": message}


# ---- the schedule is configuration ---------------------------------------------------------------


def test_the_beat_schedule_has_evaluation_by_default_and_purging_only_when_enabled() -> None:
    sched = make_celery(make_settings()).conf.beat_schedule
    assert sched["evaluate_alerts"] == {"task": EVALUATE_ALERTS, "schedule": 300.0}
    assert "purge_events" not in sched  # deleting data is opt-in
    assert {"reconcile", "dispatch"} <= set(sched)  # the existing jobs are untouched
    on = make_celery(
        make_settings(event_purge_enabled=True, event_purge_interval_seconds=3600)
    ).conf.beat_schedule
    assert on["purge_events"] == {"task": PURGE_EVENTS, "schedule": 3600.0}
    off = make_celery(make_settings(alert_evaluation_enabled=False)).conf.beat_schedule
    assert "evaluate_alerts" not in off
    assert make_celery(make_settings(alert_evaluation_interval_seconds=60)).conf.beat_schedule["evaluate_alerts"]["schedule"] == 60.0  # fmt: skip


def test_schedule_intervals_must_be_positive() -> None:
    for name in ("alert_evaluation_interval_seconds", "event_purge_interval_seconds"):
        with pytest.raises(ValueError):
            make_settings(**{name: 0})


def test_the_tasks_are_registered_under_their_names() -> None:
    assert tasks.evaluate_alert_rules.name == EVALUATE_ALERTS
    assert tasks.purge_expired_events.name == PURGE_EVENTS


# ---- evaluation ------------------------------------------------------------------------------------


def test_silence_is_raised_without_anyone_opening_the_page(lab: Lab) -> None:
    enable(lab)
    lab.s.request("POST", f"/api/v1/projects/{lab.pid}/ingest-keys", json={"label": "x"})
    svc_ingest(lab, [ev("early")], datetime.now(UTC) - timedelta(hours=8))
    assert sql(lab.e, "SELECT count(*) FROM public.alerts WHERE rule = 'telemetry_gap'") == [(0,)]
    done, failed = alerts.evaluate_scheduled(factory(lab.e), lab.e.app.state.settings)
    assert (done, failed) == (1, 0)
    assert sql(lab.e, "SELECT count(*) FROM public.alerts WHERE rule = 'telemetry_gap'") == [(1,)]
    alerts.evaluate_scheduled(factory(lab.e), lab.e.app.state.settings)  # idempotent
    assert sql(lab.e, "SELECT count(*), max(occurrences) FROM public.alerts WHERE rule = 'telemetry_gap'") == [(1, 2)]  # fmt: skip


def test_model_cost_is_evaluated_for_projects_with_usage_even_without_ingestion(lab: Lab) -> None:
    usage(lab, cost=1.5)  # ingestion is off for this project
    done, _ = alerts.evaluate_scheduled(factory(lab.e), lab.e.app.state.settings)
    assert done == 1
    assert sql(lab.e, "SELECT count(*) FROM public.alerts WHERE rule = 'llm_cost_spike'") == [(1,)]


def test_only_projects_that_need_it_are_evaluated(lab: Lab) -> None:
    from test_findings import World

    quiet = World(lab.e)  # no ingestion, no usage
    archived = World(lab.e)
    enable_other = archived.s.request("PUT", f"/api/v1/projects/{archived.pid}/policies/observability_ingest", json={"value": {"enabled": True}})  # fmt: skip
    assert enable_other.status_code == 200
    sql(lab.e, "UPDATE public.projects SET status = 'archived', archived_at = now() WHERE id = %s", archived.pid)  # fmt: skip
    old_usage = sql(lab.e, "INSERT INTO public.llm_usage (project_id, purpose, model, outcome, created_at) VALUES (%s, 'planning', 'm', 'ok', now() - interval '5 days') RETURNING 1", quiet.pid)  # fmt: skip
    assert old_usage
    with factory(lab.e)() as db:
        ids = {str(i) for i in repo.projects_for_scheduled_rules(db)}
    assert ids == set()  # nothing enabled, nothing recent, and the archived project is skipped
    enable(lab)
    with factory(lab.e)() as db:
        assert {str(i) for i in repo.projects_for_scheduled_rules(db)} == {lab.pid}


def test_one_failing_project_does_not_stop_the_others(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    from test_findings import World

    other = World(lab.e)
    for w in (lab, other):
        pid = w.pid
        sql(lab.e, "INSERT INTO public.llm_usage (project_id, purpose, model, outcome) VALUES (%s, 'planning', 'm', 'ok')", pid)  # fmt: skip
    real = alerts.evaluate_time_rules
    seen: list[uuid.UUID] = []

    def flaky(db, settings, project_id, now):  # type: ignore[no-untyped-def]
        seen.append(project_id)
        if len(seen) == 1:
            raise RuntimeError("one project is broken")
        return real(db, settings, project_id, now)

    monkeypatch.setattr(alerts, "evaluate_time_rules", flaky)
    done, failed = alerts.evaluate_scheduled(factory(lab.e), lab.e.app.state.settings)
    assert (done, failed) == (1, 1) and len(seen) == 2


# ---- the task bodies ------------------------------------------------------------------------------------


def test_the_scheduled_tasks_run_the_same_services(
    lab: Lab, monkeypatch: pytest.MonkeyPatch
) -> None:
    rt = SimpleNamespace(settings=lab.e.app.state.settings, factory=factory(lab.e))
    monkeypatch.setattr(tasks, "runtime", lambda: rt)
    usage(lab, cost=2.0)
    assert tasks.evaluate_alert_rules() == 1
    assert rule_alerts(lab, "llm_cost_spike")
    enable(lab)
    key = lab.s.request("POST", f"/api/v1/projects/{lab.pid}/ingest-keys", json={"label": "k"})
    assert key.status_code == 201
    svc_ingest(lab, [ev("old")], datetime.now(UTC))
    sql(lab.e, "UPDATE public.events SET received_at = now() - interval '60 days'")
    assert tasks.purge_expired_events() >= 1  # the expired sample was deleted
    assert sql(lab.e, "SELECT count(*) FROM public.events") == [(0,)]
    assert sql(lab.e, "SELECT count(*) FROM public.event_groups") == [
        (1,)
    ]  # still within its retention
