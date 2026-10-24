"""A scripted provider and a manual clock for automated tests (no network, no sleeping).

Queue replies and errors with ``push``; every call consumes one entry and is recorded in
``calls`` so tests can check what was sent (already redacted) and which timeout applied.
"""

import json
from collections import deque
from dataclasses import dataclass
from typing import Any

from sentinel_ai.integrations.llm.errors import ProviderError, ProviderTimeout
from sentinel_ai.integrations.llm.types import ProviderRequest, ProviderResponse


class FakeClock:
    """``clock()`` and ``sleep()`` for the gateway/deadline; time moves only when told to."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


@dataclass
class Reply:
    """A scripted successful reply. ``delay`` is how long the call "takes"; if it exceeds the
    timeout the provider raises ``ProviderTimeout`` after consuming exactly the timeout."""

    text: str
    input_tokens: int | None = 100
    output_tokens: int | None = 50
    delay: float = 0.0


@dataclass
class Call:
    request: ProviderRequest
    timeout_seconds: float


class FakeProvider:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self._script: deque[Reply | ProviderError | Exception] = deque()
        self._clock = clock
        self.calls: list[Call] = []

    def push(self, item: Reply | ProviderError | Exception | dict[str, Any]) -> "FakeProvider":
        if isinstance(item, dict):
            item = Reply(json.dumps(item))
        self._script.append(item)
        return self

    def generate(self, request: ProviderRequest, timeout_seconds: float) -> ProviderResponse:
        self.calls.append(Call(request, timeout_seconds))
        if not self._script:
            raise AssertionError("FakeProvider has no scripted reply left")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        if self._clock is not None and item.delay:
            if item.delay > timeout_seconds:
                self._clock.advance(timeout_seconds)
                raise ProviderTimeout("scripted timeout")
            self._clock.advance(item.delay)
        return ProviderResponse(item.text, item.input_tokens, item.output_tokens)
