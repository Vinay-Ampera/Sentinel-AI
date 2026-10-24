"""The LLM gateway: every model call in the platform goes through ``LLMGateway.call``.

Order of work (ADR-0010): redact -> size cap -> budget check and reservation -> provider
attempts under one workflow ``Deadline`` (per-attempt timeout, bounded retries with backoff,
never past the deadline) -> parse and validate against the caller's schema -> record usage.

Accounting is written in the gateway's own short transactions, so it survives a caller's
rollback and concurrent calls see each other's reservations. Prompt text and model output are
never stored or logged: only a hash of the redacted prompt, sizes and counts.

Failures raise an ``LLMError`` subclass whose ``reason`` is a stable degraded reason; the
workflow decides how to degrade. The gateway never returns unvalidated model text.
"""

import hashlib
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from sentinel_ai.core.config import Settings
from sentinel_ai.integrations.llm import budget
from sentinel_ai.integrations.llm.deadline import Deadline
from sentinel_ai.integrations.llm.errors import (
    BudgetBlocked,
    DeadlineExceeded,
    InvalidOutput,
    LLMDisabled,
    LLMError,
    LLMTimeout,
    LLMUnavailable,
    PromptTooLarge,
    ProviderError,
)
from sentinel_ai.integrations.llm.types import (
    PURPOSES,
    CallContext,
    GatewayRequest,
    GatewayResult,
    LLMProvider,
    ProviderRequest,
    ProviderResponse,
    Redactor,
)
from sentinel_ai.repositories import identity, policies
from sentinel_ai.repositories import llm_usage as usage_repo

# An attempt shorter than this is not worth starting (connection setup alone would exceed it).
MIN_ATTEMPT_SECONDS = 0.5
MAX_BACKOFF_SECONDS = 4.0
MAX_RETRY_AFTER_SECONDS = 10.0


@dataclass(frozen=True)
class GatewayConfig:
    model: str | None
    prices: budget.Prices
    default_limits: budget.BudgetLimits
    call_timeout_seconds: float
    max_retries: int
    invalid_output_retries: int
    backoff_base_seconds: float
    max_prompt_chars: int
    max_output_tokens: int

    @classmethod
    def from_settings(cls, s: Settings) -> "GatewayConfig":
        return cls(
            model=s.gemini_model,
            prices=budget.Prices(
                s.llm_price_input_per_mtok_usd,
                s.llm_price_output_per_mtok_usd,
            ),
            default_limits=budget.BudgetLimits(
                s.llm_max_tokens_per_run,
                s.llm_max_cost_usd_per_run,
                s.llm_max_cost_usd_per_day,
            ),
            call_timeout_seconds=s.llm_call_timeout_seconds,
            max_retries=s.llm_max_retries,
            invalid_output_retries=s.llm_invalid_output_retries,
            backoff_base_seconds=s.llm_retry_backoff_base_seconds,
            max_prompt_chars=s.llm_max_prompt_chars,
            max_output_tokens=s.llm_max_output_tokens,
        )


class LLMGateway:
    def __init__(
        self,
        *,
        provider: LLMProvider | None,
        redactor: Redactor,
        session_factory: sessionmaker[Session],
        config: GatewayConfig,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if redactor is None:
            raise ValueError("an LLM gateway cannot be built without a redactor")
        # ``provider=None`` (no API key) disables model use; callers then degrade.
        self._provider = provider
        self._redactor = redactor
        self._sessions = session_factory
        self._cfg = config
        self._clock = clock
        self._sleep = sleep

    @property
    def enabled(self) -> bool:
        return self._provider is not None and bool(self._cfg.model)

    def new_deadline(self, seconds: float) -> Deadline:
        return Deadline(seconds, self._clock)

    # ---- public --------------------------------------------------------------------------

    def call(self, ctx: CallContext, req: GatewayRequest, deadline: Deadline) -> GatewayResult:
        if self._provider is None or not self._cfg.model:
            raise LLMDisabled("no model is configured")
        if req.purpose not in PURPOSES:
            raise ValueError(f"unknown purpose {req.purpose!r}")
        model = self._cfg.model

        system, rep_system = self._redactor.redact(req.system)
        prompt, rep_prompt = self._redactor.redact(req.prompt)
        redactions = dict(Counter(rep_system.counts) + Counter(rep_prompt.counts))
        if len(system) + len(prompt) > self._cfg.max_prompt_chars:
            too_large = PromptTooLarge("the prompt exceeds the configured size limit")
            too_large.redactions = redactions
            raise too_large
        schema_name = req.output_schema.__name__
        prompt_hash = hashlib.sha256(
            "\x1f".join((req.template_version, schema_name, system, prompt)).encode()
        ).hexdigest()
        max_out = min(
            req.max_output_tokens or self._cfg.max_output_tokens, self._cfg.max_output_tokens
        )
        est_in = budget.estimate_tokens(len(system) + len(prompt))
        provider_request = ProviderRequest(system, prompt, req.output_schema, max_out, model)

        try:
            invalid_left = self._cfg.invalid_output_retries
            total_attempts = 0
            while True:
                if deadline.remaining() < MIN_ATTEMPT_SECONDS:
                    raise DeadlineExceeded("the workflow deadline was reached before the call")
                usage_id = self._reserve(ctx, req, model, prompt_hash, est_in, max_out)
                started = self._clock()
                response: ProviderResponse | None = None
                attempts = 0
                try:
                    response, attempts = self._transport(provider_request, deadline)
                    total_attempts += attempts
                    result = self._validate(req.output_schema, response)
                except LLMError as exc:
                    exc.usage_id = usage_id
                    exc.redactions = redactions
                    attempts = exc.attempts or attempts
                    total_attempts += exc.attempts
                    in_tok = self._tokens(response, est_in, out=False)
                    out_tok = self._tokens(response, 0, out=True)
                    self._finalize(usage_id, in_tok, out_tok, exc.outcome, started, attempts or 1)
                    if isinstance(exc, InvalidOutput) and invalid_left > 0:
                        invalid_left -= 1
                        continue
                    raise
                except Exception:
                    # A provider bug must degrade the workflow, not crash it, and must be accounted.
                    self._finalize(usage_id, 0, 0, "provider_error", started, attempts or 1)
                    raise LLMUnavailable("unexpected provider failure", usage_id=usage_id) from None
                in_tok = self._tokens(response, est_in, out=False)
                out_tok = self._tokens(response, 0, out=True, text_len=len(response.text))
                cost = budget.estimate_cost(in_tok, out_tok, self._cfg.prices)
                latency = self._finalize(usage_id, in_tok, out_tok, "ok", started, attempts)
                return GatewayResult(
                    output=result,
                    usage_id=usage_id,
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    estimated_cost_usd=cost,
                    latency_ms=latency,
                    attempts=total_attempts,
                    prompt_hash=prompt_hash,
                    redactions=redactions,
                )
        except LLMError as exc:
            exc.redactions = exc.redactions or redactions
            raise

    # ---- budget ---------------------------------------------------------------------------

    def _reserve(
        self,
        ctx: CallContext,
        req: GatewayRequest,
        model: str,
        prompt_hash: str,
        est_in: int,
        max_out: int,
    ) -> int:
        call_cost = budget.estimate_cost(est_in, max_out, self._cfg.prices)
        with self._sessions() as db:
            usage_repo.lock_budget(db)
            limits = budget.resolve_limits(
                policies.global_rows(db),
                policies.project_rows(db, ctx.project_id) if ctx.project_id else {},
                self._cfg.default_limits,
            )
            run_tokens, run_cost = (
                usage_repo.run_totals(db, ctx.agent_run_id) if ctx.agent_run_id else (0, 0)
            )
            hit = budget.exceeded_limit(
                limits,
                run_tokens=run_tokens,
                run_cost=run_cost,  # type: ignore[arg-type]
                day_cost=usage_repo.cost_last_24h(db),
                call_tokens=est_in + max_out,
                call_cost=call_cost,
            )

            def record(
                *,
                input_tokens: int,
                output_tokens: int,
                cost_usd: float,
                blocked: bool,
                outcome: str,
            ) -> int:
                return usage_repo.insert_usage(
                    db,
                    project_id=ctx.project_id,
                    run_id=ctx.run_id,
                    requested_by=ctx.requested_by,
                    agent_run_id=ctx.agent_run_id,
                    purpose=req.purpose,
                    model=model,
                    prompt_hash=prompt_hash,
                    template_version=req.template_version,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost_usd,
                    blocked=blocked,
                    outcome=outcome,
                )

            if hit is not None:
                usage_id = record(
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=0.0,
                    blocked=True,
                    outcome="blocked_by_budget",
                )
                rc = ctx.request
                identity.insert_audit_event(
                    db,
                    actor_type="user" if ctx.requested_by else "system",
                    actor_user_id=ctx.requested_by,
                    action="llm.budget_blocked",
                    outcome="denied",
                    target_type="llm_usage",
                    target_id=str(usage_id),
                    project_id=ctx.project_id,
                    request_id=rc.request_id if rc else None,
                    ip_address=rc.ip_address if rc else None,
                    detail={
                        "limit": hit,
                        "purpose": req.purpose,
                        "estimated_tokens": est_in + max_out,
                        "estimated_cost_usd": call_cost,
                        "agent_run_id": str(ctx.agent_run_id) if ctx.agent_run_id else None,
                    },
                )
                db.commit()
                raise BudgetBlocked(f"model budget reached ({hit})", limit=hit, usage_id=usage_id)
            usage_id = record(
                input_tokens=est_in,
                output_tokens=max_out,
                cost_usd=call_cost,
                blocked=False,
                outcome="reserved",
            )
            db.commit()
            return usage_id

    def _finalize(
        self, usage_id: int, in_tok: int, out_tok: int, outcome: str, started: float, attempts: int
    ) -> int:
        latency = max(0, int((self._clock() - started) * 1000))
        cost = budget.estimate_cost(in_tok, out_tok, self._cfg.prices)
        with self._sessions() as db:
            usage_repo.finalize_usage(
                db,
                usage_id,
                input_tokens=in_tok,
                output_tokens=out_tok,
                cost_usd=cost,
                outcome=outcome,
                latency_ms=latency,
                attempts=attempts,
            )
            db.commit()
        return latency

    @staticmethod
    def _tokens(
        response: ProviderResponse | None, estimate: int, *, out: bool, text_len: int = 0
    ) -> int:
        """Provider-reported tokens when given, else an estimate. A call that produced no
        response (timeout, outage) is recorded as using none."""
        if response is None:
            return 0
        reported = response.output_tokens if out else response.input_tokens
        if reported is not None:
            return max(0, reported)
        return budget.estimate_tokens(len(response.text)) if out else estimate

    # ---- transport ------------------------------------------------------------------------

    def _transport(
        self, request: ProviderRequest, deadline: Deadline
    ) -> tuple[ProviderResponse, int]:
        """Call the provider with bounded retries; never starts or sleeps past the deadline."""
        assert self._provider is not None
        attempts = 0
        last: ProviderError | None = None
        while True:
            remaining = deadline.remaining()
            if remaining < MIN_ATTEMPT_SECONDS:
                break
            attempts += 1
            try:
                response = self._provider.generate(
                    request, min(self._cfg.call_timeout_seconds, remaining)
                )
                return response, attempts
            except ProviderError as exc:
                last = exc
                if not exc.retryable or attempts > self._cfg.max_retries:
                    break
                delay = min(
                    self._cfg.backoff_base_seconds * 2 ** (attempts - 1), MAX_BACKOFF_SECONDS
                )
                if exc.retry_after:
                    delay = min(max(delay, exc.retry_after), MAX_RETRY_AFTER_SECONDS)
                if deadline.remaining() - delay < MIN_ATTEMPT_SECONDS:
                    break
                self._sleep(delay)
        if last is None:
            raise DeadlineExceeded("the workflow deadline was reached before the call")
        error: LLMError = (
            LLMTimeout("the model did not answer in time")
            if last.outcome == "timeout"
            else LLMUnavailable("the model is unavailable")
        )
        error.outcome = last.outcome
        error.attempts = attempts
        raise error

    @staticmethod
    def _validate(schema: type[BaseModel], response: ProviderResponse) -> BaseModel:
        try:
            return schema.model_validate_json(response.text)
        except (ValidationError, ValueError):
            # No detail on purpose: validation messages can quote the model's text.
            raise InvalidOutput("the model output did not match the required schema") from None
