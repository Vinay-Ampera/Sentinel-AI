"""Gateway building blocks that need no database: budgets, the fake provider, the Gemini
adapter (with an injected fake client: no network, no key) and the single-import rule."""

import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from google.genai import errors as genai_errors
from pydantic import BaseModel, ConfigDict, SecretStr

from sentinel_ai.integrations.llm import budget
from sentinel_ai.integrations.llm.deadline import Deadline
from sentinel_ai.integrations.llm.errors import (
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from sentinel_ai.integrations.llm.fake import FakeClock, FakeProvider, Reply
from sentinel_ai.integrations.llm.gemini import GeminiProvider, translate_error
from sentinel_ai.integrations.llm.types import ProviderRequest
from support import make_settings

LIMITS = budget.BudgetLimits(1000, 1.0, 5.0)
SRC = Path(__file__).resolve().parents[2] / "src" / "sentinel_ai"


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


def req() -> ProviderRequest:
    return ProviderRequest("sys", "hello", Out, 256, "some-model")


# ---- budget ------------------------------------------------------------------------------


def test_lowest_limit_wins_across_settings_global_and_project_policy() -> None:
    glob = {"llm_limits": {"max_tokens_per_run": 500, "max_cost_usd_per_run": 9.0}}
    proj = {"llm_limits": {"max_tokens_per_run": 800, "max_cost_usd_per_day": 2.0}}
    got = budget.resolve_limits(glob, proj, LIMITS)
    assert got == budget.BudgetLimits(500, 1.0, 2.0)  # a project can never loosen anything


@pytest.mark.parametrize("bad", [0, -5, "9", None, True, [1], {"a": 1}])
def test_malformed_policy_values_are_ignored(bad: object) -> None:
    got = budget.resolve_limits({"llm_limits": {"max_tokens_per_run": bad}}, {}, LIMITS)
    assert got == LIMITS
    assert budget.resolve_limits({"llm_limits": "nope"}, {}, LIMITS) == LIMITS


def test_exceeded_limit_names_the_limit_and_allows_exact_fit() -> None:
    def check(**kw: object) -> str | None:
        base: dict = dict(run_tokens=0, run_cost=Decimal(0), day_cost=Decimal(0), call_tokens=1, call_cost=0.0)  # fmt: skip
        return budget.exceeded_limit(LIMITS, **{**base, **kw})

    assert check(call_tokens=1000) is None
    assert check(call_tokens=1001) == "max_tokens_per_run"
    assert check(run_tokens=900, call_tokens=101) == "max_tokens_per_run"
    assert check(call_cost=1.0) is None
    assert check(call_cost=1.01) == "max_cost_usd_per_run"
    assert check(day_cost=Decimal("4.5"), call_cost=0.6) == "max_cost_usd_per_day"
    assert check(run_cost=Decimal("0.9"), call_cost=0.2) == "max_cost_usd_per_run"


def test_cost_estimate_uses_prices_per_million_tokens() -> None:
    prices = budget.Prices(2.0, 10.0)
    assert budget.estimate_cost(1_000_000, 100_000, prices) == 3.0
    assert budget.estimate_cost(0, 0, prices) == 0.0
    assert budget.estimate_tokens(0) == 1
    assert budget.estimate_tokens(7) == 3  # rounds up, 3 chars per token


# ---- deadline and fake provider -----------------------------------------------------------


def test_deadline_counts_down_with_the_clock() -> None:
    clock = FakeClock()
    d = Deadline(10, clock)
    clock.advance(4)
    assert d.remaining() == 6 and not d.expired()
    clock.advance(7)
    assert d.remaining() == 0 and d.expired()


def test_fake_provider_replays_script_and_times_out_on_slow_reply() -> None:
    clock = FakeClock()
    p = FakeProvider(clock).push({"answer": "a"}).push(Reply('{"answer":"b"}', delay=9))
    assert p.generate(req(), 5).text == '{"answer": "a"}'
    with pytest.raises(ProviderTimeout):
        p.generate(req(), 5)
    assert clock.now == 1005.0  # consumed exactly the timeout, not the full delay
    assert [c.timeout_seconds for c in p.calls] == [5, 5]
    with pytest.raises(AssertionError):
        p.generate(req(), 5)


# ---- Gemini adapter -----------------------------------------------------------------------


class FakeModels:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response, self.error, self.kwargs = response, error, {}

    def generate_content(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def provider(models: FakeModels) -> GeminiProvider:
    return GeminiProvider(SecretStr("not-a-real-key"), client=SimpleNamespace(models=models))


def usage(**kw: int | None) -> SimpleNamespace:
    base = dict(prompt_token_count=10, candidates_token_count=5, thoughts_token_count=None)
    return SimpleNamespace(**{**base, **kw})


def test_gemini_adapter_passes_timeout_schema_and_counts_thinking_tokens() -> None:
    models = FakeModels(SimpleNamespace(text='{"answer":"x"}', usage_metadata=usage(thoughts_token_count=7)))  # fmt: skip
    got = provider(models).generate(req(), 12.5)
    assert (got.text, got.input_tokens, got.output_tokens) == ('{"answer":"x"}', 10, 12)
    cfg = models.kwargs["config"]
    assert cfg.http_options.timeout == 12500  # milliseconds
    assert cfg.http_options.retry_options.attempts == 1  # the SDK must not retry on its own
    assert cfg.response_mime_type == "application/json"
    assert "answer" in cfg.system_instruction and models.kwargs["model"] == "some-model"
    assert models.kwargs["contents"] == "hello"


def test_gemini_unreported_usage_stays_unknown() -> None:
    resp = SimpleNamespace(text="{}", usage_metadata=usage(prompt_token_count=None, candidates_token_count=None))  # fmt: skip
    got = provider(FakeModels(resp)).generate(req(), 5)
    assert got.input_tokens is None and got.output_tokens is None


def test_gemini_empty_or_blocked_response_is_rejected() -> None:
    with pytest.raises(ProviderRejected):
        provider(FakeModels(SimpleNamespace(text=None, usage_metadata=None))).generate(req(), 5)


@pytest.mark.parametrize(
    ("exc", "expected", "retryable"),
    [
        (genai_errors.APIError(429, {}), ProviderRateLimited, True),
        (genai_errors.ServerError(503, {}), ProviderUnavailable, True),
        (genai_errors.APIError(504, {}), ProviderTimeout, True),
        (genai_errors.ClientError(400, {}), ProviderRejected, False),
        (genai_errors.ClientError(403, {}), ProviderRejected, False),
        (httpx.ReadTimeout("slow"), ProviderTimeout, True),
        (httpx.ConnectError("down"), ProviderUnavailable, True),
        (RuntimeError("boom"), ProviderRejected, False),
    ],
)
def test_sdk_errors_translate_to_retryable_or_permanent(exc: Exception, expected: type, retryable: bool) -> None:  # fmt: skip
    got = translate_error(exc)
    assert type(got) is expected and got.retryable is retryable


def test_translated_errors_do_not_carry_sdk_messages() -> None:
    secret = "key=AIzaSyFAKEFAKEFAKE"
    models = FakeModels(error=genai_errors.ClientError(400, {"error": {"message": secret}}))
    with pytest.raises(ProviderRejected) as err:
        provider(models).generate(req(), 5)
    assert secret not in str(err.value) and err.value.__cause__ is None


# ---- structural rules ---------------------------------------------------------------------


def test_only_the_gemini_module_imports_the_sdk() -> None:
    offenders = [
        str(p.relative_to(SRC))
        for p in SRC.rglob("*.py")
        if re.search(r"^\s*(from|import)\s+google(\.genai|\s+import\s+genai)", p.read_text(), re.M)
        and p.name != "gemini.py"
    ]
    assert offenders == []


def test_llm_settings_defaults_and_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    s = make_settings()
    assert s.llm_max_retries == 2 and s.llm_call_timeout_seconds <= s.llm_graph_deadline_seconds
    assert s.gemini_api_key is None  # nothing configured unless the environment provides it
    with pytest.raises(ValueError, match="LLM_MAX_RETRIES"):
        make_settings(llm_max_retries=9)
    with pytest.raises(ValueError, match="LLM_CALL_TIMEOUT"):
        make_settings(llm_call_timeout_seconds=90, llm_graph_deadline_seconds=60)
    with pytest.raises(ValueError):
        make_settings(llm_max_cost_usd_per_day=0)
