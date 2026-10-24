"""Verification agent: a limitations-aware summary of a re-scan comparison.

The verdict is computed by code (``compare``). The model, when asked, only words the summary;
it has no field that could change a finding's status."""

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.agents.common import EvidenceId, cites_only, one_line
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.types import GatewayRequest

TEMPLATE_VERSION = "verification-v1"
EVIDENCE_CHARS = 8_000
MAX_OUTPUT_TOKENS = 700
TOOL_CHECK = {
    "bandit": "bandit_static",
    "semgrep": "semgrep_static",
    "dependency_audit": "dependency_audit",
}
NO_REVERIFY = frozenset({"false_positive", "accepted_risk"})

SYSTEM = (
    "You summarise the outcome of re-scanning a project to check whether a security finding is "
    "fixed. Use only the evidence blocks. Explain the outcome in plain words and list the "
    "limitations that apply (for example: absence from a static scan does not prove the "
    "weakness is gone). Do not recommend closing or accepting the finding; people decide that."
)


class VerificationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome_text: str = Field(min_length=1, max_length=600)
    limitations: list[str] = Field(min_length=1, max_length=5)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=6)


def compare(
    *,
    finding_status: str,
    last_run_id: str | None,
    run_id: str,
    attempt_outcome: str | None,
    result_status: str | None,
) -> tuple[str, str]:
    """Verdict and reason, from stored records only."""
    if result_status is None:
        return "inconclusive", "The run has no result for the re-scan check."
    if result_status not in ("passed", "failed"):
        return "inconclusive", f"The re-scan did not complete normally (status {result_status})."
    if attempt_outcome == "fixed":
        return (
            "fixed_by_rescan",
            "A complete re-scan of the same source no longer reports the finding.",
        )
    if last_run_id == run_id:
        return "still_present", "The re-scan reported the finding again."
    return "inconclusive", (
        "The re-scan recorded no verification attempt: it may not have been a complete scan of "
        f"the finding's source, so absence proves nothing (finding status {finding_status})."
    )


def input_hash(finding_id: str, run_id: str, verdict: str, model: str | None) -> str:
    return hashlib.sha256(
        "\x1f".join((TEMPLATE_VERSION, model or "", finding_id, run_id, verdict)).encode()
    ).hexdigest()


def build_request(items: list[ef.Excerpt], verdict: str) -> tuple[GatewayRequest, ef.EvidenceBlock]:
    block = ef.build_evidence_block("verification", items, max_total_chars=EVIDENCE_CHARS)
    body = (
        f"The computed verdict is '{verdict}'. Summarise it as JSON "
        '{"outcome_text", "limitations", "evidence_ids"}.\n\n' + block.text
    )
    request = GatewayRequest(
        purpose="verification",
        template_version=TEMPLATE_VERSION,
        system=ef.with_data_rule(SYSTEM),
        prompt=body,
        output_schema=VerificationSummary,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return request, block


def validate(out: VerificationSummary, shown: set[str]) -> dict[str, Any] | None:
    if not cites_only(out.evidence_ids, shown):
        return None
    return {
        "outcome_text": one_line(out.outcome_text, 600),
        "limitations": [one_line(x, 300) for x in out.limitations],
        "evidence_ids": list(out.evidence_ids),
    }
