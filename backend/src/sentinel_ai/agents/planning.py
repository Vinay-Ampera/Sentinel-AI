"""Planning agent: the prompt, output schema and evidence for choosing catalog checks.

The model may only *select* among catalog check ids and give a short reason for each. It has
no field for risk, approval, commands, parameters or targets; those come from the catalog and
policy code after the choice (``check_catalog.from_check_ids`` and ``plans.store_plan``).
"""

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.types import GatewayRequest
from sentinel_ai.services.check_catalog import CATALOG, PlanContext

TEMPLATE_VERSION = "planning-v1"
MAX_REQUEST_CHARS = 2000
MAX_REASON_CHARS = 300
MAX_OUTPUT_TOKENS = 700
MAX_CHOICES = 10
EVIDENCE_CHARS = 12_000  # ADR-0010: focused excerpts, 12 kB of prompt data

SYSTEM = (
    "You help a QA engineer choose which automated checks to run on a software project. "
    "You are given a catalog of available checks, facts from a static analysis of the project "
    "and the engineer's request. Select the catalog checks that best serve the request. "
    "Rules: use only check ids that appear in the catalog; do not invent checks, commands, "
    "parameters, targets or risk levels; select at most "
    f"{MAX_CHOICES}; give each a one-sentence reason that refers to the request or the "
    "project facts; if nothing in the catalog fits the request, return an empty list."
)


class PlanChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    check_id: str = Field(min_length=1, max_length=60, pattern=r"^[a-z0-9_]+$")
    reason: str = Field(min_length=1, max_length=MAX_REASON_CHARS)


class PlanProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    checks: list[PlanChoice] = Field(max_length=MAX_CHOICES)


def selectable_checks(application_type: str) -> list[str]:
    """Catalog ids a model may be offered: the same set the keyword path can select."""
    return [
        spec.check_id
        for spec in CATALOG.values()
        if spec.automatic
        and spec.check_id != "custom_script"
        and application_type in spec.app_types
    ]


def catalog_excerpts(application_type: str) -> list[ef.Excerpt]:
    out = []
    for check_id in selectable_checks(application_type):
        spec = CATALOG[check_id]
        text = f"{spec.name} [{spec.category}]: {spec.summary}"
        out.append(ef.Excerpt(f"check:{check_id}", "catalog_check", text, priority=5))
    return out


_FACT_FIELDS = ("languages", "frameworks", "test_tools", "coverage_tools", "config_files")


def fact_excerpt(ctx: PlanContext) -> ef.Excerpt | None:
    facts = ef.pick(ctx.facts(), _FACT_FIELDS)
    if not facts:
        return None
    return ef.Excerpt(
        "fact:analysis", "analysis_fact", json.dumps(facts, sort_keys=True), priority=8
    )


def input_hash(prompt: str, ctx: PlanContext, model: str | None) -> str:
    """Cache key: same request, same offered catalog, same analysis facts, same template."""
    parts = [
        TEMPLATE_VERSION,
        model or "",
        " ".join(prompt.split()).lower(),
        ",".join(selectable_checks(ctx.application_type)),
        json.dumps(ef.pick(ctx.facts(), _FACT_FIELDS), sort_keys=True),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def build_request(prompt: str, ctx: PlanContext) -> tuple[GatewayRequest, ef.EvidenceBlock]:
    items = [ef.Excerpt("request:user", "user_request", prompt[:MAX_REQUEST_CHARS], priority=10)]
    items += catalog_excerpts(ctx.application_type)
    fact = fact_excerpt(ctx)
    if fact is not None:
        items.append(fact)
    block = ef.build_evidence_block("planning", items, max_total_chars=EVIDENCE_CHARS)
    body = (
        "Choose catalog checks for the request in the 'request:user' block. Reply with a JSON "
        'object {"checks": [{"check_id": "<catalog id without the check: prefix>", "reason": '
        '"..."}]}.\n\n' + block.text
    )
    request = GatewayRequest(
        purpose="planning",
        template_version=TEMPLATE_VERSION,
        system=ef.with_data_rule(SYSTEM),
        prompt=body,
        output_schema=PlanProposal,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return request, block


def validate_choices(
    proposal: PlanProposal, application_type: str
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Keep only offered catalog ids (first reason wins); report each rejected choice."""
    offered = set(selectable_checks(application_type))
    kept: dict[str, str] = {}
    rejected: list[dict[str, Any]] = []
    for choice in proposal.checks:
        cid = choice.check_id
        if cid not in offered:
            rejected.append({"check_id": cid, "why": "not an offered catalog check"})
        elif cid in kept:
            rejected.append({"check_id": cid, "why": "duplicate"})
        else:
            kept[cid] = " ".join(choice.reason.split())[:MAX_REASON_CHARS]
    return kept, rejected
