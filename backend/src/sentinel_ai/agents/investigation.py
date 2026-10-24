"""Investigation agent: ranked, evidence-cited hypotheses for a failed result or a finding.

The failure *class* is decided by code from stored statuses and messages. The model is called
only for classes where interpretation helps; it can only add hypotheses that cite the evidence
it was shown and can never mark anything confirmed."""

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.agents.common import EvidenceId, cites_only, one_line
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.types import GatewayRequest

TEMPLATE_VERSION = "investigation-v1"
EVIDENCE_CHARS = 14_000
MAX_OUTPUT_TOKENS = 1200
LIMITATIONS = (
    "These are hypotheses ranked from stored evidence only. Nothing was re-run and no cause is "
    "confirmed; reproduce the failure before acting on any of them."
)

# status/class -> (class, explanation, ask the model?)
_NOT_RUN = {"failed_to_start", "timed_out", "cancelled", "blocked", "skipped", "not_run"}
MODEL_CLASSES = frozenset(
    {"assertion_failure", "unclassified", "scanner_finding", "reported_error"}
)

SYSTEM = (
    "You help a QA engineer understand why a test failed or why a scanner reported a finding. "
    "Use only the evidence blocks. Propose up to 5 plausible causes, most likely first. Each "
    "cause must cite the evidence ids it rests on and may be labelled 'likely' (the evidence "
    "points to it) or 'hypothesis' (plausible, not shown). Never claim a cause is confirmed. "
    "Give short reproduction steps a person could follow. If the evidence does not support any "
    "cause, return an empty list."
)


class Cause(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: Literal["likely", "hypothesis"]
    statement: str = Field(min_length=1, max_length=400)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=6)
    reproduction_steps: list[str] = Field(max_length=5)


class InvestigationOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    causes: list[Cause] = Field(max_length=5)


def classify(status: str | None, messages: list[str], *, is_finding: bool) -> tuple[str, str]:
    """Deterministic failure class and a plain explanation."""
    if is_finding:
        return "scanner_finding", "A scanner reported this; the evidence is the tool's own output."
    if status == "passed":
        return "not_a_failure", "This result passed; there is nothing to investigate."
    if status == "failed_to_start":
        return (
            "infrastructure",
            "The test never started (sandbox or runner problem); it says nothing about the code.",
        )
    if status == "timed_out":
        return "timeout", "The test hit its time limit."
    if status in _NOT_RUN:
        return "not_executed", f"The test was not executed ({status})."
    text = " ".join(messages).lower()
    if any(k in text for k in ("modulenotfounderror", "importerror", "no module named")):
        return (
            "missing_dependency",
            "A module could not be imported; the offline sandbox installs no dependencies (Q66).",
        )
    if "syntaxerror" in text:
        return "syntax_error", "Python reported a syntax error in the project or its tests."
    if "assert" in text:
        return "assertion_failure", "An assertion in a test did not hold."
    if "timeout" in text or "timed out" in text:
        return "timeout", "A test reported a timeout."
    return "unclassified", "The failure does not match a known pattern."


def classify_alert(has_group: bool) -> tuple[str, str]:
    """Class for an alert subject that carries reported application events. Alerts about a
    measurement only (silence, dropped events, a rate) are explained, never sent to a model."""
    if has_group:
        return (
            "reported_error",
            "The application reported this error; Sentinel did not observe it itself, and "
            "reported events can be incomplete or wrong.",
        )
    return (
        "no_failure_evidence",
        "This alert reports a measurement (a count, a silence or dropped events). It carries no "
        "error text to investigate; open the group or the run it points to instead.",
    )


def input_hash(subject: str, content_sha: str, model: str | None) -> str:
    return hashlib.sha256(
        "\x1f".join((TEMPLATE_VERSION, model or "", subject, content_sha)).encode()
    ).hexdigest()


def build_request(
    items: list[ef.Excerpt], classification: str
) -> tuple[GatewayRequest, ef.EvidenceBlock]:
    block = ef.build_evidence_block("investigation", items, max_total_chars=EVIDENCE_CHARS)
    body = (
        f"The deterministic failure class is '{classification}'. Propose causes as JSON "
        '{"causes": [{"label", "statement", "evidence_ids", "reproduction_steps"}]}.\n\n'
        + block.text
    )
    request = GatewayRequest(
        purpose="investigation",
        template_version=TEMPLATE_VERSION,
        system=ef.with_data_rule(SYSTEM),
        prompt=body,
        output_schema=InvestigationOut,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return request, block


def validate(out: InvestigationOut, shown: set[str]) -> tuple[list[dict[str, Any]], int]:
    kept, dropped = [], 0
    for cause in out.causes:
        if not cites_only(cause.evidence_ids, shown):
            dropped += 1
            continue
        kept.append(
            {
                "label": cause.label,
                "statement": one_line(cause.statement, 400),
                "evidence_ids": list(cause.evidence_ids),
                "reproduction_steps": [one_line(s, 200) for s in cause.reproduction_steps],
            }
        )
    return kept, dropped
