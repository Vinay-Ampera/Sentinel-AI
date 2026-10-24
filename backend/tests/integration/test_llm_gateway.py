"""LLM gateway against a real (disposable) database and the fake provider. No network, no key.

Time is a manual clock, so deadline and backoff behaviour is exact and nothing sleeps."""

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from typing import Any

import psycopg
import pytest
from pydantic import BaseModel, ConfigDict
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.integrations.llm import budget
from sentinel_ai.integrations.llm.deadline import Deadline
from sentinel_ai.integrations.llm.errors import (
    BudgetBlocked,
    DeadlineExceeded,
    InvalidOutput,
    LLMDisabled,
    LLMTimeout,
    LLMUnavailable,
    PromptTooLarge,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from sentinel_ai.integrations.llm.fake import FakeClock, FakeProvider, Reply
from sentinel_ai.integrations.llm.gateway import GatewayConfig, LLMGateway
from sentinel_ai.integrations.llm.types import (
    CallContext,
    GatewayRequest,
    RedactionReport,
)
from sentinel_ai.services.audit import RequestContext

TEST_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_URL, reason="TEST_DATABASE_URL not set")


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


class MaskSecrets:
    """Test redactor: stands in for the Step 3 implementation."""

    def redact(self, text: str) -> tuple[str, RedactionReport]:
        n = text.count("SECRET-TOKEN")
        return text.replace("SECRET-TOKEN", "[redacted]"), RedactionReport(
            {"token": n} if n else {}
        )


CONFIG = GatewayConfig(
    model="test-model",
    prices=budget.Prices(1.0, 10.0),
    default_limits=budget.BudgetLimits(200_000, 2.0, 20.0),
    call_timeout_seconds=30.0,
    max_retries=2,
    invalid_output_retries=1,
    backoff_base_seconds=0.5,
    max_prompt_chars=2000,
    max_output_tokens=500,
)


class Env:
    def __init__(self, conn: psycopg.Connection, factory: sessionmaker[Session]) -> None:
        self.pg, self.factory = conn, factory
        self.clock = FakeClock()
        self.provider = FakeProvider(self.clock)
        self.user = conn.execute(
            "INSERT INTO app_user.users (email, display_name, password_hash) "
            "VALUES (%s, 'T', 'x') RETURNING id", (f"t{uuid.uuid4().hex[:8]}@example.test",),
        ).fetchone()[0]  # type: ignore[index]  # fmt: skip
        self.project = conn.execute(
            "INSERT INTO public.projects (name, owner_user_id, application_type) "
            "VALUES (%s, %s, 'rest_api') RETURNING id", (f"p{uuid.uuid4().hex[:8]}", self.user),
        ).fetchone()[0]  # type: ignore[index]  # fmt: skip
        self.ctx = CallContext(self.project, self.user, request=RequestContext("req-1", "127.0.0.1", "t"))  # fmt: skip

    def gateway(self, provider: Any = "default", **cfg: Any) -> LLMGateway:
        prov = self.provider if provider == "default" else provider
        return LLMGateway(
            provider=prov, redactor=MaskSecrets(), session_factory=self.factory,
            config=replace(CONFIG, **cfg), clock=self.clock, sleep=self.clock.sleep,
        )  # fmt: skip

    def agent_run(self) -> uuid.UUID:
        return self.pg.execute(
            "INSERT INTO public.agent_runs (project_id, workflow, requested_by) "
            "VALUES (%s, 'planning', %s) RETURNING id", (self.project, self.user),
        ).fetchone()[0]  # type: ignore[index]  # fmt: skip

    def usage(self) -> list[dict[str, Any]]:
        cur = self.pg.execute("SELECT * FROM public.llm_usage ORDER BY id")
        cols = [c.name for c in cur.description or []]
        return [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]

    def deadline(self, seconds: float = 60.0) -> Any:
        return Deadline(seconds, self.clock)


def request(prompt: str = "classify this", **kw: Any) -> GatewayRequest:
    return GatewayRequest("planning", "plan-v1", "You are a planner.", prompt, Out, **kw)


@pytest.fixture
def env(migrated_db: str) -> Iterator[Env]:
    engine = create_engine(migrated_db.replace("postgresql://", "postgresql+psycopg://"))
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        name = conn.execute("SELECT current_database()").fetchone()
        assert name and name[0].endswith("_test")
        conn.execute("TRUNCATE app_user.users, public.projects, public.audit_events CASCADE")
        yield Env(conn, sessionmaker(bind=engine, expire_on_commit=False))
    engine.dispose()


# ---- success and accounting ---------------------------------------------------------------


def test_success_validates_output_and_records_usage(env: Env) -> None:
    env.provider.push(Reply('{"answer": "ok"}', input_tokens=1000, output_tokens=200, delay=1.5))
    result = env.gateway().call(env.ctx, request(), env.deadline())
    assert result.output == Out(answer="ok")
    (row,) = env.usage()
    assert row["outcome"] == "ok" and row["attempts"] == 1 and row["latency_ms"] == 1500
    assert (row["input_tokens"], row["output_tokens"]) == (1000, 200)
    assert float(row["estimated_cost_usd"]) == pytest.approx(0.003)  # 1000*1/1e6 + 200*10/1e6
    assert (row["project_id"], row["requested_by"], row["purpose"]) == (env.project, env.user, "planning")  # fmt: skip
    assert row["model"] == "test-model" and row["template_version"] == "plan-v1"
    assert len(row["prompt_hash"]) == 64 and row["blocked_by_budget"] is False
    assert result.usage_id == row["id"] and result.prompt_hash == row["prompt_hash"]


def test_prompt_is_redacted_before_sending_and_never_stored(env: Env) -> None:
    env.provider.push({"answer": "ok"})
    env.gateway().call(env.ctx, request("token=SECRET-TOKEN please"), env.deadline())
    sent = env.provider.calls[0].request
    assert "SECRET-TOKEN" not in sent.prompt and "[redacted]" in sent.prompt
    dump = json.dumps(env.usage(), default=str)
    assert "SECRET-TOKEN" not in dump and "please" not in dump  # only the hash is kept


def test_missing_provider_usage_is_estimated_and_agent_run_is_linked(env: Env) -> None:
    run = env.agent_run()
    env.provider.push(Reply('{"answer": "ok"}', input_tokens=None, output_tokens=None))
    ctx = CallContext(env.project, env.user, agent_run_id=run)
    env.gateway().call(ctx, request(), env.deadline())
    (row,) = env.usage()
    assert row["agent_run_id"] == run and row["input_tokens"] > 0 and row["output_tokens"] > 0


# ---- refusals before any call -------------------------------------------------------------


def test_disabled_gateway_makes_no_call_and_no_row(env: Env) -> None:
    for gw in (env.gateway(provider=None), env.gateway(model=None)):
        with pytest.raises(LLMDisabled) as err:
            gw.call(env.ctx, request(), env.deadline())
        assert err.value.reason == "llm_disabled"
    assert env.provider.calls == [] and env.usage() == []


def test_oversized_prompt_is_refused_not_truncated(env: Env) -> None:
    with pytest.raises(PromptTooLarge):
        env.gateway().call(env.ctx, request("x" * 2001), env.deadline())
    assert env.provider.calls == [] and env.usage() == []


def test_expired_deadline_blocks_the_call(env: Env) -> None:
    deadline = env.deadline(5)
    env.clock.advance(4.8)
    with pytest.raises(DeadlineExceeded):
        env.gateway().call(env.ctx, request(), deadline)
    assert env.provider.calls == [] and env.usage() == []


# ---- budgets ------------------------------------------------------------------------------


def _blocked_audit(env: Env) -> list[tuple]:
    return env.pg.execute(
        "SELECT actor_user_id, outcome, project_id, detail FROM public.audit_events "
        "WHERE action = 'llm.budget_blocked'"
    ).fetchall()


def test_run_token_budget_blocks_records_and_audits(env: Env) -> None:
    run = env.agent_run()
    ctx = CallContext(env.project, env.user, agent_run_id=run, request=env.ctx.request)
    gw = env.gateway(default_limits=budget.BudgetLimits(900, 2.0, 20.0))
    env.provider.push(Reply('{"answer": "ok"}', input_tokens=300, output_tokens=100))
    gw.call(ctx, request(), env.deadline())  # reserved ~510 (fits), settles at 400
    with pytest.raises(BudgetBlocked) as err:
        gw.call(ctx, request(max_output_tokens=500), env.deadline())  # 400 + ~510 > 900
    assert err.value.reason == "budget_blocked" and err.value.limit == "max_tokens_per_run"
    assert len(env.provider.calls) == 1  # the blocked call never reached the provider
    rows = env.usage()
    assert rows[1]["blocked_by_budget"] is True and rows[1]["outcome"] == "blocked_by_budget"
    assert err.value.usage_id == rows[1]["id"]
    ((actor, outcome, project, detail),) = _blocked_audit(env)
    assert (actor, outcome, project) == (env.user, "denied", env.project)
    assert detail["limit"] == "max_tokens_per_run" and detail["agent_run_id"] == str(run)
    assert "prompt" not in json.dumps(detail)


def test_day_budget_counts_other_runs_and_in_flight_reservations(env: Env) -> None:
    # Another caller already holds a reservation worth almost the whole daily budget.
    env.pg.execute(
        "INSERT INTO public.llm_usage (project_id, purpose, model, input_tokens, output_tokens, "
        "estimated_cost_usd, outcome) VALUES (%s, 'planning', 'm', 10, 10, 19.9999, 'reserved')",
        (env.project,),
    )
    with pytest.raises(BudgetBlocked) as err:
        env.gateway().call(env.ctx, request(), env.deadline())
    assert err.value.limit == "max_cost_usd_per_day" and env.provider.calls == []
    # Old usage (older than 24 h) and blocked rows do not count.
    env.pg.execute("UPDATE public.llm_usage SET created_at = now() - interval '25 hours' WHERE NOT blocked_by_budget")  # fmt: skip
    env.provider.push({"answer": "ok"})
    env.gateway().call(env.ctx, request(), env.deadline())


def test_project_policy_can_only_tighten_the_budget(env: Env) -> None:
    env.pg.execute(
        "INSERT INTO public.policies (scope, project_id, key, value) VALUES "
        "('project', %s, 'llm_limits', '{\"max_cost_usd_per_run\": 0.0001, \"max_tokens_per_run\": 99999999}')",
        (env.project,),
    )
    run = env.agent_run()
    ctx = CallContext(env.project, env.user, agent_run_id=run)
    with pytest.raises(BudgetBlocked) as err:
        env.gateway().call(ctx, request(), env.deadline())
    assert err.value.limit == "max_cost_usd_per_run"
    # The huge project token value did not loosen the settings/global ceiling.
    gw = env.gateway(default_limits=budget.BudgetLimits(10, 2.0, 20.0))
    env.pg.execute("DELETE FROM public.policies WHERE scope = 'project'")
    with pytest.raises(BudgetBlocked) as err2:
        gw.call(ctx, request(), env.deadline())
    assert err2.value.limit == "max_tokens_per_run"


# ---- retries, timeouts and the workflow deadline ------------------------------------------


def test_transient_failures_retry_with_backoff_then_succeed(env: Env) -> None:
    env.provider.push(ProviderTimeout()).push(ProviderUnavailable()).push({"answer": "ok"})
    result = env.gateway().call(env.ctx, request(), env.deadline())
    assert result.attempts == 3 and env.clock.sleeps == [0.5, 1.0]
    assert [r["outcome"] for r in env.usage()] == ["ok"] and env.usage()[0]["attempts"] == 3


def test_retries_are_bounded_and_reported(env: Env) -> None:
    for _ in range(5):
        env.provider.push(ProviderTimeout())
    with pytest.raises(LLMTimeout) as err:
        env.gateway().call(env.ctx, request(), env.deadline())
    assert len(env.provider.calls) == 3  # 1 + max_retries
    assert err.value.reason == "llm_timeout"
    (row,) = env.usage()
    assert row["outcome"] == "timeout" and row["attempts"] == 3 and row["input_tokens"] == 0


def test_rate_limit_honours_retry_after_and_exhausts_as_unavailable(env: Env) -> None:
    env.provider.push(ProviderRateLimited(retry_after=3.0)).push({"answer": "ok"})
    env.gateway().call(env.ctx, request(), env.deadline())
    assert env.clock.sleeps == [3.0]
    for _ in range(3):
        env.provider.push(ProviderRateLimited())
    with pytest.raises(LLMUnavailable) as err:
        env.gateway().call(env.ctx, request(), env.deadline())
    assert err.value.reason == "llm_unavailable" and env.usage()[-1]["outcome"] == "rate_limited"


def test_permanent_provider_error_is_not_retried(env: Env) -> None:
    env.provider.push(ProviderRejected("bad request"))
    with pytest.raises(LLMUnavailable):
        env.gateway().call(env.ctx, request(), env.deadline())
    assert len(env.provider.calls) == 1 and env.clock.sleeps == []
    assert env.usage()[0]["outcome"] == "provider_error"


def test_unexpected_provider_exception_degrades_and_is_accounted(env: Env) -> None:
    env.provider.push(RuntimeError("sdk bug with details"))
    with pytest.raises(LLMUnavailable) as err:
        env.gateway().call(env.ctx, request(), env.deadline())
    assert "details" not in str(err.value) and err.value.__cause__ is None
    assert env.usage()[0]["outcome"] == "provider_error"  # reservation was settled, not left open


def test_each_attempt_timeout_is_capped_by_the_remaining_deadline(env: Env) -> None:
    deadline = env.deadline(10)
    env.provider.push(Reply("{}", delay=99)).push(Reply("{}", delay=99)).push(Reply("{}", delay=99))
    start = env.clock.now
    with pytest.raises(LLMTimeout):
        env.gateway(call_timeout_seconds=4.0).call(env.ctx, request(), deadline)
    # 4s, sleep 0.5, 4s, sleep 1.0, then only 0.5s are left: the last attempt is shrunk to
    # that, and the whole call ends exactly at the deadline, never after it.
    assert [c.timeout_seconds for c in env.provider.calls] == [4.0, 4.0, 0.5]
    assert env.clock.now - start == 10.0


def test_retries_never_run_past_the_overall_deadline(env: Env) -> None:
    deadline = env.deadline(3)
    for _ in range(4):
        env.provider.push(Reply("{}", delay=99))
    start = env.clock.now
    with pytest.raises(LLMTimeout):
        env.gateway(call_timeout_seconds=2.0, backoff_base_seconds=1.0).call(env.ctx, request(), deadline)  # fmt: skip
    # attempt 1 uses 2s, 1s remain; backoff 1s would leave 0s (< minimum): no second attempt.
    assert len(env.provider.calls) == 1 and env.clock.now - start <= 3.0
    assert env.clock.sleeps == []


def test_second_attempt_timeout_shrinks_to_what_is_left(env: Env) -> None:
    deadline = env.deadline(6)
    env.provider.push(Reply("{}", delay=99)).push({"answer": "ok"})
    env.gateway(call_timeout_seconds=3.0).call(env.ctx, request(), deadline)
    assert [c.timeout_seconds for c in env.provider.calls] == [3.0, 2.5]  # 6 - 3 - 0.5 slept


# ---- invalid output -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    ["not json", "[]", '{"answer": 5}', '{"answer": "x", "approve": true}', '{"answer": "x"', ""],
)
def test_invalid_output_is_rejected_without_echoing_it(env: Env, bad: str) -> None:
    env.provider.push(Reply(bad)).push(Reply(bad))
    with pytest.raises(InvalidOutput) as err:
        env.gateway().call(env.ctx, request(), env.deadline())
    assert err.value.reason == "invalid_output"
    assert "approve" not in str(err.value) and "not json" not in str(err.value)
    assert [r["outcome"] for r in env.usage()] == ["invalid_output", "invalid_output"]
    assert len(env.provider.calls) == 2  # exactly one repair-free retry, then stop


def test_invalid_output_retry_can_succeed_and_both_calls_are_billed(env: Env) -> None:
    env.provider.push(Reply("garbage", input_tokens=10, output_tokens=5)).push({"answer": "ok"})
    result = env.gateway().call(env.ctx, request(), env.deadline())
    assert result.output == Out(answer="ok")
    assert [r["outcome"] for r in env.usage()] == ["invalid_output", "ok"]
    assert env.usage()[0]["output_tokens"] == 5


def test_invalid_output_retry_is_budget_checked_again(env: Env) -> None:
    run = env.agent_run()
    ctx = CallContext(env.project, env.user, agent_run_id=run)
    gw = env.gateway(default_limits=budget.BudgetLimits(700, 2.0, 20.0))
    env.provider.push(Reply("garbage", input_tokens=300, output_tokens=200)).push({"answer": "ok"})
    with pytest.raises(BudgetBlocked):  # 500 used + a second ~510 reservation > 700
        gw.call(ctx, request(), env.deadline())
    assert len(env.provider.calls) == 1


# ---- redaction through the real redactor (Step 3) -------------------------------------------


def _real_gateway(env: Env, secrets: tuple[str, ...] = ()) -> LLMGateway:
    from sentinel_ai.integrations.llm.redaction import PromptRedactor

    return LLMGateway(
        provider=env.provider, redactor=PromptRedactor(secrets), session_factory=env.factory,
        config=CONFIG, clock=env.clock, sleep=env.clock.sleep,
    )  # fmt: skip


def test_real_redactor_in_the_gateway_strips_prompt_and_system_and_reports_counts(env: Env) -> None:  # fmt: skip
    env.provider.push({"answer": "ok"})
    gw = _real_gateway(env, ("pepper-value-123456",))
    req = GatewayRequest(
        "planning", "plan-v1", "System key=AIzaSyA1234567890abcdefghijklmnopqrstuv",
        "log: password=hunter2xx pepper-value-123456 mail a@b.io", Out,
    )  # fmt: skip
    result = gw.call(env.ctx, req, env.deadline())
    sent = env.provider.calls[0].request
    for leaked in ("AIzaSyA", "hunter2xx", "pepper-value-123456", "a@b.io"):
        assert leaked not in sent.system + sent.prompt
    assert result.redactions == {"google_key": 1, "pair": 1, "configured_secret": 1, "email": 1}
    dump = json.dumps(env.usage(), default=str)
    assert "hunter2xx" not in dump and "pepper-value" not in dump


def test_hash_is_of_the_redacted_prompt_so_secrets_never_influence_it(env: Env) -> None:
    env.provider.push({"answer": "ok"}).push({"answer": "ok"})
    gw = _real_gateway(env)
    a = gw.call(env.ctx, request("check password=first-secret-1"), env.deadline())
    b = gw.call(env.ctx, request("check password=other-secret-2"), env.deadline())
    assert a.prompt_hash == b.prompt_hash  # both redact to the same text


def test_redaction_counts_ride_on_failures_too(env: Env) -> None:
    gw = _real_gateway(env)
    env.provider.push(ProviderRejected("no"))
    with pytest.raises(LLMUnavailable) as err:
        gw.call(env.ctx, request("password=abcdef123"), env.deadline())
    assert err.value.redactions == {"pair": 1}
    with pytest.raises(PromptTooLarge) as big:
        gw.call(env.ctx, request("password=abcdef123 " + "x" * 2100), env.deadline())
    assert big.value.redactions == {"pair": 1}


def test_a_gateway_cannot_be_built_without_a_redactor(env: Env) -> None:
    with pytest.raises(ValueError, match="redactor"):
        LLMGateway(provider=env.provider, redactor=None, session_factory=env.factory, config=CONFIG)  # type: ignore[arg-type]  # fmt: skip
