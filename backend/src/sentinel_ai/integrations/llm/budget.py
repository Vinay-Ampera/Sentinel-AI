"""Token and cost budgets for model calls (pure functions; the gateway supplies the numbers).

Limits come from the ``llm_limits`` policy (global row, then the project row, which may only
be stricter) and from the ``LLM_MAX_*`` settings; the **lowest** value of each limit wins, so
neither the database policy nor the operator's environment can be exceeded by the other.
Cost is an estimate: providers report tokens, and the price per million tokens is configured.
"""

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# Characters per token used to size a prompt before sending it; deliberately low (so the
# estimate is high) to stay on the safe side of the budget.
CHARS_PER_TOKEN = 3


@dataclass(frozen=True)
class BudgetLimits:
    max_tokens_per_run: int
    max_cost_usd_per_run: float
    max_cost_usd_per_day: float


@dataclass(frozen=True)
class Prices:
    input_per_mtok_usd: float
    output_per_mtok_usd: float


def estimate_tokens(chars: int) -> int:
    return max(1, math.ceil(chars / CHARS_PER_TOKEN))


def estimate_cost(input_tokens: int, output_tokens: int, prices: Prices) -> float:
    cost = (
        input_tokens * prices.input_per_mtok_usd + output_tokens * prices.output_per_mtok_usd
    ) / 1_000_000
    return round(cost, 6)


def _positive_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        return None
    return float(value)


def resolve_limits(
    global_rows: dict[str, Any],
    project_rows: dict[str, Any],
    default: BudgetLimits,
) -> BudgetLimits:
    """Lowest valid value per limit across settings, the global policy and the project policy.
    Malformed policy values are ignored (the stricter remaining source still applies)."""
    values: dict[str, list[float]] = {
        "max_tokens_per_run": [float(default.max_tokens_per_run)],
        "max_cost_usd_per_run": [default.max_cost_usd_per_run],
        "max_cost_usd_per_day": [default.max_cost_usd_per_day],
    }
    for rows in (global_rows, project_rows):
        policy = rows.get("llm_limits")
        if isinstance(policy, dict):
            for key, bucket in values.items():
                number = _positive_number(policy.get(key))
                if number is not None:
                    bucket.append(number)
    return BudgetLimits(
        max_tokens_per_run=int(min(values["max_tokens_per_run"])),
        max_cost_usd_per_run=min(values["max_cost_usd_per_run"]),
        max_cost_usd_per_day=min(values["max_cost_usd_per_day"]),
    )


def exceeded_limit(
    limits: BudgetLimits,
    *,
    run_tokens: int,
    run_cost: Decimal,
    day_cost: Decimal,
    call_tokens: int,
    call_cost: float,
) -> str | None:
    """Name of the first limit the call would break, or ``None`` if it fits."""
    if run_tokens + call_tokens > limits.max_tokens_per_run:
        return "max_tokens_per_run"
    if run_cost + Decimal(str(call_cost)) > Decimal(str(limits.max_cost_usd_per_run)):
        return "max_cost_usd_per_run"
    if day_cost + Decimal(str(call_cost)) > Decimal(str(limits.max_cost_usd_per_day)):
        return "max_cost_usd_per_day"
    return None
