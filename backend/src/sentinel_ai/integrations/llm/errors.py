"""Failure types of the LLM gateway.

Provider errors say whether a retry can help; gateway errors carry a stable ``reason`` that
workflows record as the ``degraded_reason`` of an agent run. Messages never contain prompt
text, model output or credentials.
"""


class ProviderError(Exception):
    """Raised by a provider. ``retryable`` tells the gateway whether another attempt may help."""

    retryable = False
    outcome = "provider_error"

    def __init__(self, message: str = "", *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderTimeout(ProviderError):
    retryable = True
    outcome = "timeout"


class ProviderRateLimited(ProviderError):
    retryable = True
    outcome = "rate_limited"


class ProviderUnavailable(ProviderError):
    retryable = True
    outcome = "unavailable"


class ProviderRejected(ProviderError):
    """Permanent: bad request, bad credentials, blocked content. Never retried."""

    retryable = False
    outcome = "provider_error"


class LLMError(Exception):
    """A model step could not produce a validated result. Workflows degrade on this."""

    reason = "llm_unavailable"
    outcome = "provider_error"  # the ``llm_usage.outcome`` recorded for this failure

    def __init__(self, message: str = "", *, usage_id: int | None = None) -> None:
        super().__init__(message or self.reason)
        self.usage_id = usage_id
        self.attempts = 0  # provider attempts spent before giving up
        self.redactions: dict[str, int] = {}  # what was removed from the prompt (counts only)


class LLMDisabled(LLMError):
    reason = "llm_disabled"


class BudgetBlocked(LLMError):
    reason = "budget_blocked"
    outcome = "blocked_by_budget"

    def __init__(self, message: str, *, limit: str, usage_id: int | None = None) -> None:
        super().__init__(message, usage_id=usage_id)
        self.limit = limit


class DeadlineExceeded(LLMError):
    reason = "deadline_exceeded"
    outcome = "deadline_exceeded"


class PromptTooLarge(LLMError):
    reason = "prompt_too_large"


class LLMTimeout(LLMError):
    reason = "llm_timeout"
    outcome = "timeout"


class LLMUnavailable(LLMError):
    reason = "llm_unavailable"


class InvalidOutput(LLMError):
    reason = "invalid_output"
    outcome = "invalid_output"
