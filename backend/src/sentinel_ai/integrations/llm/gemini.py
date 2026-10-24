"""Gemini provider (google-genai SDK). The only module allowed to import the SDK.

It makes a single attempt per call with the timeout the gateway gives it (SDK-level retries are
switched off; retries, deadlines and budgets belong to the gateway). Errors are translated to
``ProviderError`` subclasses using status codes and exception classes only: SDK messages can
echo request details, so they are never copied into our errors or logs.
"""

import json
from typing import Any

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types
from pydantic import SecretStr

from sentinel_ai.integrations.llm.errors import (
    ProviderError,
    ProviderRateLimited,
    ProviderRejected,
    ProviderTimeout,
    ProviderUnavailable,
)
from sentinel_ai.integrations.llm.types import ProviderRequest, ProviderResponse

_JSON_RULE = (
    "Reply with one JSON object only, no markdown and no commentary, that validates against "
    "this JSON Schema:\n"
)


def translate_error(exc: Exception) -> ProviderError:
    """Map an SDK/transport exception to a gateway-level provider error (value-free)."""
    if isinstance(exc, httpx.TimeoutException | TimeoutError):
        return ProviderTimeout("request timed out")
    if isinstance(exc, genai_errors.APIError):
        code = exc.code if isinstance(exc.code, int) else 0
        if code == 429:
            return ProviderRateLimited("rate limited")
        if code in (408, 504):
            return ProviderTimeout(f"upstream timeout ({code})")
        if code >= 500:
            return ProviderUnavailable(f"upstream error ({code})")
        return ProviderRejected(f"request rejected ({code})")
    if isinstance(exc, httpx.TransportError | ConnectionError | OSError):
        return ProviderUnavailable("transport error")
    return ProviderRejected(f"unexpected provider failure ({type(exc).__name__})")


class GeminiProvider:
    def __init__(self, api_key: SecretStr, client: Any | None = None) -> None:
        # ``client`` is injectable so tests never construct a real SDK client with a real key.
        self._client = client or genai.Client(
            api_key=api_key.get_secret_value(),
            http_options=genai_types.HttpOptions(
                retry_options=genai_types.HttpRetryOptions(attempts=1)
            ),
        )

    def generate(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        schema = json.dumps(request.output_schema.model_json_schema(), separators=(",", ":"))
        config = genai_types.GenerateContentConfig(
            system_instruction=f"{request.system}\n\n{_JSON_RULE}{schema}",
            max_output_tokens=request.max_output_tokens,
            response_mime_type="application/json",
            temperature=0.2,
            http_options=genai_types.HttpOptions(
                timeout=max(1, int(timeout_seconds * 1000)),
                retry_options=genai_types.HttpRetryOptions(attempts=1),
            ),
        )
        try:
            response = self._client.models.generate_content(
                model=request.model, contents=request.prompt, config=config
            )
        except Exception as exc:  # translated; the original is not chained (it may hold details)
            raise translate_error(exc) from None
        text = response.text
        if not text:
            # Blocked by safety filters, truncated before any text, or an empty candidate.
            raise ProviderRejected("empty or blocked response")
        usage = response.usage_metadata
        input_tokens = getattr(usage, "prompt_token_count", None)
        out = getattr(usage, "candidates_token_count", None)
        thoughts = getattr(usage, "thoughts_token_count", None)
        # Reasoning tokens are billed as output; count them so budgets are not under-counted.
        output_tokens = None if out is None and thoughts is None else (out or 0) + (thoughts or 0)
        return ProviderResponse(text, input_tokens, output_tokens)
