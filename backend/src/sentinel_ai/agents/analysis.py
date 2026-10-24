"""Analysis agent: an interpretation of a deterministic project analysis (Stage 5 output).

The interpretation is shown beside the facts, inferences and gaps and never replaces them.
Every claim must cite the evidence ids it rests on; claims that cite nothing the model was
shown are dropped, and each is labelled ``inference`` or ``hypothesis`` (never ``fact``)."""

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.agents.common import EvidenceId, cites_only, one_line, token
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.types import GatewayRequest

TEMPLATE_VERSION = "analysis-v1"
EVIDENCE_CHARS = 12_000
MAX_OUTPUT_TOKENS = 1400
FACT_KEYS = (
    "archive",
    "languages",
    "frameworks",
    "test_tools",
    "coverage_tools",
    "config_files",
    "manifests",
    "lockfiles",
    "package_scripts",
    "test_files",
)

SYSTEM = (
    "You explain the architecture of a software project to a QA engineer, using only the "
    "analysis evidence you are given (facts detected by static analysis, inferences made from "
    "them, and known gaps). Describe the main components, likely trust boundaries and the "
    "uncertainties. Rules: every statement must cite evidence ids from the evidence blocks; "
    "label each statement 'inference' (follows from the evidence) or 'hypothesis' (plausible "
    "but not shown); never state something as fact; never claim behaviour that static "
    "analysis cannot show; if the evidence is thin, say so in the uncertainties."
)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    label: Literal["inference", "hypothesis"]
    basis: list[EvidenceId] = Field(min_length=1, max_length=6)


class Uncertainty(BaseModel):
    model_config = ConfigDict(extra="forbid")
    statement: str = Field(min_length=1, max_length=300)
    label: Literal["inference", "hypothesis"]
    basis: list[EvidenceId] = Field(min_length=1, max_length=6)


class AnalysisInterpretation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=1200)
    summary_basis: list[EvidenceId] = Field(min_length=1, max_length=6)
    components: list[Claim] = Field(max_length=8)
    trust_boundaries: list[Claim] = Field(max_length=6)
    uncertainties: list[Uncertainty] = Field(max_length=8)


def excerpts(detected: dict[str, Any]) -> list[ef.Excerpt]:
    out: list[ef.Excerpt] = []
    facts = detected.get("facts", {})
    for key in FACT_KEYS:
        if key in facts and facts[key] not in (None, [], {}):
            text = json.dumps(facts[key], sort_keys=True, default=str)
            out.append(ef.Excerpt(f"fact:{key}", "analysis_fact", text, priority=6))
    for item in detected.get("inferences", []):
        text = (
            f"{item.get('statement', '')} (confidence {item.get('confidence', '?')}; "
            f"basis {item.get('basis', [])})"
        )
        out.append(
            ef.Excerpt(
                f"inference:{token(str(item.get('id', 'x')))}", "analysis_fact", text, priority=8
            )
        )
    for gap in detected.get("gaps", []):
        text = f"{gap.get('what', '')}: {gap.get('why', '')}"
        out.append(
            ef.Excerpt(f"gap:{token(str(gap.get('id', 'x')))}", "analysis_fact", text, priority=7)
        )
    return out


def input_hash(snapshot_sha: str | None, snapshot_id: str, model: str | None) -> str:
    return hashlib.sha256(
        "\x1f".join((TEMPLATE_VERSION, model or "", snapshot_sha or snapshot_id)).encode()
    ).hexdigest()


def build_request(detected: dict[str, Any]) -> tuple[GatewayRequest, ef.EvidenceBlock]:
    block = ef.build_evidence_block("analysis", excerpts(detected), max_total_chars=EVIDENCE_CHARS)
    body = (
        "Interpret this project analysis. Reply with one JSON object with keys summary, "
        "summary_basis, components, trust_boundaries, uncertainties (see the schema). Cite "
        "evidence ids exactly as they appear in the blocks.\n\n" + block.text
    )
    request = GatewayRequest(
        purpose="analysis",
        template_version=TEMPLATE_VERSION,
        system=ef.with_data_rule(SYSTEM),
        prompt=body,
        output_schema=AnalysisInterpretation,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return request, block


def validate(out: AnalysisInterpretation, shown: set[str]) -> tuple[dict[str, Any] | None, int]:
    """(clean output, dropped claim count). The summary must rest on shown evidence or the
    whole answer is unusable; claims that cite anything else are dropped one by one."""
    if not cites_only(out.summary_basis, shown):
        return None, 0
    dropped = 0

    def keep(items: list[Any], text_field: str) -> list[dict[str, Any]]:
        nonlocal dropped
        kept = []
        for item in items:
            if cites_only(item.basis, shown):
                data = item.model_dump()
                for key in ("name", "description", "statement"):
                    if key in data:
                        data[key] = one_line(data[key], 300)
                kept.append(data)
            else:
                dropped += 1
        return kept

    return {
        "summary": one_line(out.summary, 1200),
        "summary_basis": list(out.summary_basis),
        "components": keep(out.components, "description"),
        "trust_boundaries": keep(out.trust_boundaries, "description"),
        "uncertainties": keep(out.uncertainties, "statement"),
    }, dropped
