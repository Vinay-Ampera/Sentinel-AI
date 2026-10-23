"""Deterministic catalog of checks and the plan generator (Stage 6).

The catalog is data, not model output: every planned test comes from an entry here, with
risk, prerequisites and expected evidence fixed by code. A prompt or a developer can only
*select* catalog entries and supply bounded, validated parameters; neither can introduce a
command, lower a risk level, or skip an approval. Nothing here executes anything.

Statuses assigned to proposals (planned_tests.status):
  planned   - applicable and its prerequisites are met by recorded evidence;
  skipped   - not applicable to this project (reason says why);
  deferred  - applicable but a prerequisite is missing (reason says what to provide);
  blocked   - set later by the authorization gate (policy / target not authorized).
"""

import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

RISK_ORDER = ("low", "medium", "high", "critical")
# What each level means in this catalog. Risk is assigned by code from these definitions
# (never by a prompt, a developer or a model); policy then decides who approves what.
RISK_DEFINITIONS = {
    "low": "Reads source or sends only passive, read-only traffic to a local target; no network egress, no changes to any system.",
    "medium": "Needs outbound network access, drives a UI or probes an AI endpoint on a local target, or sends any traffic to a shared remote environment. Side effects are possible but bounded.",
    "high": "Intrusive, attack-style, load-generating or developer-supplied code, or an active check against a shared remote environment. Can alter data or degrade a system.",
    "critical": "Destructive or production-affecting. Reserved: no catalog check is critical, and production testing is blocked by default.",
}
MAX_TESTS_PER_PLAN = 60
MAX_PARAMS = 5
PATH_PARAM = re.compile(r"^(?!/)(?!.*\.\.)[A-Za-z0-9_./-]{1,200}$")
# A single leading slash only: "//host" would be read as a network-path reference.
URL_PATH_PARAM = re.compile(r"^/(?!/)[A-Za-z0-9_./~%-]{0,198}$")

CODE = "code"
URL = "url"
SANDBOX_STAGE_NOTE = (
    "Execution of every check arrives with the sandbox and runner stages (8-10); approving a "
    "plan authorizes a later run, it does not start one."
)


def max_risk(*levels: str) -> str:
    return max(levels, key=RISK_ORDER.index)


@dataclass(frozen=True)
class SourceInfo:
    id: uuid.UUID
    source_type: str  # git_repository | zip_upload | localhost_url | remote_url
    name: str
    environment: str | None  # local | development | staging | production | None

    @property
    def kind(self) -> str:
        return URL if self.source_type in ("localhost_url", "remote_url") else CODE


@dataclass(frozen=True)
class PlanContext:
    application_type: str
    snapshot_id: uuid.UUID | None
    detected: dict[str, Any] | None  # analysis result of a *completed* snapshot, if any
    snapshot_source_id: uuid.UUID | None
    sources: tuple[SourceInfo, ...]  # active sources only

    def facts(self) -> dict[str, Any]:
        facts: dict[str, Any] = (self.detected or {}).get("facts", {})
        return facts

    def has_analysis(self) -> bool:
        return self.detected is not None


@dataclass(frozen=True)
class Verdict:
    status: str  # planned | skipped | deferred
    reason: str


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    name: str
    category: str
    tool: str
    base_risk: str
    target_kind: str
    app_types: frozenset[str]
    summary: str
    prerequisites: tuple[str, ...]
    expected_evidence: tuple[str, ...]
    keywords: tuple[str, ...]
    evaluate: Callable[[PlanContext, "SourceInfo | None"], Verdict]
    active_on_target: bool = False  # sends traffic that may change or load the target
    needs_egress: bool = False
    always_requires_approval: bool = False
    developer_selectable: bool = True
    automatic: bool = True  # False: never proposed in automatic or prompt plans


@dataclass(frozen=True)
class Proposal:
    check_id: str
    name: str
    category: str
    tool: str
    origin: str  # recommended | prompt | developer_defined
    risk_level: str
    status: str
    rationale: str
    definition: dict[str, Any]
    source_id: uuid.UUID | None
    script_artifact_id: uuid.UUID | None = None
    always_requires_approval: bool = False
    warnings: list[str] = field(default_factory=list)


# ---- evaluation helpers ------------------------------------------------------------


def _names(items: list[dict[str, Any]]) -> set[str]:
    return {str(i.get("name")) for i in items}


def _langs(ctx: PlanContext) -> set[str]:
    return _names(ctx.facts().get("languages", []))


def _needs_analysis(ctx: PlanContext) -> Verdict | None:
    if not ctx.has_analysis():
        return Verdict(
            "deferred",
            "No completed analysis exists; run a project analysis first so this check can be matched to evidence.",
        )
    return None


def _eval_pytest(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    if "python" not in _langs(ctx):
        return Verdict("skipped", "Not applicable: no Python source was detected.")
    facts = ctx.facts()
    py_tests = [p for p in facts.get("test_files", {}).get("examples", []) if p.endswith(".py")]
    if "pytest" in _names(facts.get("test_tools", [])) or py_tests:
        return Verdict(
            "planned",
            "Python tests were detected"
            + (f" ({len(py_tests)} example file(s), e.g. {py_tests[0]})." if py_tests else "."),
        )
    return Verdict("deferred", "Python code was found but no Python tests were detected.")


def _eval_js_tests(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    facts = ctx.facts()
    langs = _langs(ctx)
    if not langs & {"javascript", "typescript"}:
        return Verdict("skipped", "Not applicable: no JavaScript/TypeScript source was detected.")
    runners = _names(facts.get("test_tools", [])) & {"jest", "vitest", "mocha", "jasmine"}
    scripts = [k for k in facts.get("package_scripts", {}) if k.endswith("#test")]
    if runners or scripts:
        basis = sorted(runners) or [s.split("#")[0] for s in scripts]
        return Verdict(
            "planned", f"A JavaScript test runner or test script was detected ({', '.join(basis)})."
        )
    return Verdict(
        "deferred", "JavaScript code was found but no test runner or test script was detected."
    )


def _eval_openapi_lint(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    if "openapi_spec" in ctx.facts().get("config_files", {}):
        return Verdict("planned", "An OpenAPI/Swagger specification file was detected.")
    return Verdict(
        "deferred",
        "No OpenAPI/Swagger specification was detected; add one to enable contract checks.",
    )


def _eval_semgrep(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    if not ctx.facts().get("languages"):
        return Verdict("skipped", "Not applicable: no analysable source languages were detected.")
    return Verdict("planned", "Source code was detected; static analysis needs no running target.")


def _eval_bandit(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    if "python" not in _langs(ctx):
        return Verdict(
            "skipped", "Not applicable: Bandit analyses Python source and none was detected."
        )
    return Verdict("planned", "Python source was detected.")


def _eval_sandbox_smoke(_ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if target is None or target.source_type != "zip_upload":
        return Verdict(
            "deferred",
            "Only an uploaded ZIP archive can be checked in the sandbox so far; Git sources "
            "need the sandboxed clone step.",
        )
    return Verdict(
        "planned",
        "Checks that the sandbox can unpack this archive and lists what it contains. "
        "It does not run any of the project's code.",
    )


def _eval_dependency_audit(ctx: PlanContext, _t: SourceInfo | None) -> Verdict:
    if (v := _needs_analysis(ctx)) is not None:
        return v
    facts = ctx.facts()
    if not facts.get("manifests"):
        return Verdict("skipped", "Not applicable: no dependency manifests were detected.")
    if not facts.get("lockfiles"):
        return Verdict(
            "deferred",
            "Dependency manifests exist but no lockfile was detected, so audited versions would not be reproducible.",
        )
    return Verdict("planned", "Dependency manifests and lockfiles were detected.")


def _url_target(ctx: PlanContext, target: SourceInfo | None) -> Verdict | None:
    if target is None:
        return Verdict(
            "deferred",
            "Needs a running target: register a localhost or approved development/staging URL source.",
        )
    return None


def _app_type_fit(ctx: PlanContext, allowed: set[str], label: str) -> Verdict | None:
    if ctx.application_type not in allowed:
        return Verdict(
            "skipped",
            f"Not applicable: {label} applies to {', '.join(sorted(allowed))} projects, this project is declared as {ctx.application_type}.",
        )
    return None


def _eval_http_smoke(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    return _url_target(ctx, target) or Verdict(
        "planned",
        f"Target '{target.name if target else ''}' is registered; read-only GET requests only.",
    )


def _eval_playwright(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if (v := _app_type_fit(ctx, {"web_app"}, "browser flow tests")) is not None:
        return v
    if (v := _url_target(ctx, target)) is not None:
        return v
    cfg = ctx.facts().get("config_files", {}) if ctx.has_analysis() else {}
    if "e2e_config" in cfg:
        return Verdict(
            "planned", "An end-to-end test configuration was detected and a target is registered."
        )
    return Verdict(
        "deferred",
        "No Playwright/Cypress configuration was detected; add one or define the flows manually.",
    )


def _eval_axe(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if (v := _app_type_fit(ctx, {"web_app"}, "accessibility checks")) is not None:
        return v
    return _url_target(ctx, target) or Verdict(
        "planned",
        "A web application with a registered target; axe-core covers only automatically detectable issues.",
    )


def _eval_zap(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if (v := _app_type_fit(ctx, {"web_app", "rest_api", "ai_app"}, "dynamic scans")) is not None:
        return v
    return _url_target(ctx, target) or Verdict(
        "planned", "A target is registered; this variant observes responses without attacking."
    )


def _eval_zap_active(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    base = _eval_zap(ctx, target)
    if base.status != "planned":
        return base
    return Verdict(
        "planned",
        "Intrusive scan: sends attack-style requests to the target; needs explicit approval and target authorization.",
    )


def _eval_load(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    return _url_target(ctx, target) or Verdict(
        "planned",
        "Generates sustained load against the target; bounded by duration and request-rate limits.",
    )


def _eval_llm(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if (v := _app_type_fit(ctx, {"ai_app"}, "LLM security probes")) is not None:
        return v
    return _url_target(ctx, target) or Verdict(
        "planned",
        "An AI application with a registered target; probes send adversarial prompts to its endpoint.",
    )


def _eval_agent(ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    return _eval_llm(ctx, target)


def _eval_custom(_ctx: PlanContext, _target: SourceInfo | None) -> Verdict:
    return Verdict(
        "planned",
        "Developer-supplied script; runs only inside the sandbox and always needs approval.",
    )


_ALL = frozenset({"web_app", "rest_api", "ai_app"})

CATALOG: dict[str, CheckSpec] = {
    spec.check_id: spec
    for spec in (
        CheckSpec(
            "pytest_unit",
            "Python unit tests (pytest)",
            "functional",
            "pytest",
            "low",
            CODE,
            _ALL,
            "Runs the project's own pytest suite in the sandbox.",
            ("Project dependencies installable in the sandbox",),
            ("JUnit XML report", "exit code", "captured log"),
            ("pytest", "unit", "python", "functional", "tests"),
            _eval_pytest,
        ),
        CheckSpec(
            "js_unit",
            "JavaScript unit tests",
            "functional",
            "npm_test",
            "low",
            CODE,
            _ALL,
            "Runs the project's own JavaScript/TypeScript test script in the sandbox.",
            ("Project dependencies installable in the sandbox",),
            ("test report", "exit code", "captured log"),
            ("jest", "vitest", "javascript", "typescript", "unit", "functional", "tests"),
            _eval_js_tests,
        ),
        CheckSpec(
            "openapi_lint",
            "OpenAPI specification lint",
            "api",
            "openapi_lint",
            "low",
            CODE,
            frozenset({"rest_api", "web_app", "ai_app"}),
            "Statically validates the API specification file; sends no traffic.",
            ("An OpenAPI/Swagger file in the source",),
            ("lint report",),
            ("openapi", "swagger", "api", "contract", "spec"),
            _eval_openapi_lint,
        ),
        CheckSpec(
            "semgrep_static",
            "Static security analysis (Semgrep)",
            "security",
            "semgrep",
            "low",
            CODE,
            _ALL,
            "Pattern-based source scan; findings are unverified leads, not confirmed vulnerabilities.",
            ("Source code available in the sandbox",),
            ("SARIF/JSON scanner output",),
            ("semgrep", "static", "sast", "security", "vulnerab"),
            _eval_semgrep,
        ),
        CheckSpec(
            "bandit_static",
            "Python security lint (Bandit)",
            "security",
            "bandit",
            "low",
            CODE,
            _ALL,
            "Python-specific security lint; findings are unverified leads.",
            ("Python source available in the sandbox",),
            ("JSON scanner output",),
            ("bandit", "python", "security", "static"),
            _eval_bandit,
        ),
        CheckSpec(
            "sandbox_smoke",
            "Sandbox self-check (archive unpack and file census)",
            "functional",
            "sandbox",
            "low",
            CODE,
            _ALL,
            "Unpacks the uploaded archive in a disposable, network-less container and counts the "
            "files. Proves the sandbox path end to end; no project code is executed.",
            ("Uploaded ZIP source", "JOB_EXECUTOR=docker and the sandbox image"),
            ("file census (JSON)", "exit code", "captured log", "sandbox manifest"),
            (),
            _eval_sandbox_smoke,
            automatic=False,
        ),
        CheckSpec(
            "dependency_audit",
            "Dependency vulnerability audit",
            "security",
            "dependency_audit",
            "medium",
            CODE,
            _ALL,
            "Compares locked dependency versions with an advisory database; needs outbound access to the advisory feed.",
            ("Lockfile present", "Egress allow-list entry for the advisory feed"),
            ("audit report", "advisory identifiers"),
            ("dependency", "dependencies", "audit", "cve", "supply", "vulnerab"),
            _eval_dependency_audit,
            needs_egress=True,
        ),
        CheckSpec(
            "http_smoke",
            "HTTP smoke checks",
            "api",
            "http_probe",
            "low",
            URL,
            _ALL,
            "Read-only GET requests to confirm key endpoints respond.",
            ("A reachable target URL source",),
            ("request/response summaries (redacted)", "status codes"),
            ("smoke", "http", "endpoint", "endpoints", "health", "api", "availability"),
            _eval_http_smoke,
        ),
        CheckSpec(
            "playwright_e2e",
            "Browser flow tests (Playwright)",
            "ui",
            "playwright",
            "medium",
            URL,
            frozenset({"web_app"}),
            "Drives the web UI through user flows; interactions may create data on the target.",
            ("A reachable target URL source", "Flow definitions or Playwright config"),
            ("screenshots", "trace", "test report"),
            ("playwright", "e2e", "end-to-end", "browser", "ui", "flow", "flows"),
            _eval_playwright,
            active_on_target=True,
        ),
        CheckSpec(
            "axe_accessibility",
            "Accessibility scan (axe-core)",
            "accessibility",
            "axe_core",
            "low",
            URL,
            frozenset({"web_app"}),
            "Automated accessibility rules on rendered pages; manual review is still required.",
            ("A reachable target URL source",),
            ("axe result JSON", "affected elements and criteria"),
            ("axe", "accessibility", "a11y", "wcag"),
            _eval_axe,
        ),
        CheckSpec(
            "zap_baseline",
            "Passive security baseline (OWASP ZAP)",
            "security",
            "owasp_zap_baseline",
            "medium",
            URL,
            _ALL,
            "Observes responses for missing headers and similar issues without attacking.",
            ("A reachable target URL source", "Authorized target scope"),
            ("ZAP report", "alert list with evidence"),
            ("zap", "owasp", "baseline", "passive", "headers", "dynamic", "security"),
            _eval_zap,
        ),
        CheckSpec(
            "zap_active",
            "Active security scan (OWASP ZAP)",
            "security",
            "owasp_zap_active",
            "high",
            URL,
            _ALL,
            "Intrusive: sends attack-style requests that can alter data or load the target.",
            ("A reachable target URL source", "Authorized target scope allowing high risk"),
            ("ZAP report", "alert list with evidence"),
            ("zap active", "active scan", "intrusive", "penetration", "pentest"),
            _eval_zap_active,
            active_on_target=True,
            always_requires_approval=True,
        ),
        CheckSpec(
            "load_basic",
            "Basic load test",
            "performance",
            "load_test",
            "high",
            URL,
            _ALL,
            "Sustained request volume against the target; can degrade a shared environment.",
            ("A reachable target URL source", "Agreed rate and duration limits"),
            ("latency percentiles", "error rate"),
            ("load", "performance", "stress", "latency", "throughput"),
            _eval_load,
            active_on_target=True,
            always_requires_approval=True,
        ),
        CheckSpec(
            "llm_prompt_injection",
            "LLM prompt-injection probes",
            "llm_security",
            "llm_probe",
            "medium",
            URL,
            frozenset({"ai_app"}),
            "Sends adversarial prompts to the application's AI endpoint and records responses.",
            ("A reachable target URL source", "Documented AI endpoint"),
            ("prompt/response pairs (redacted)", "pass/fail per probe"),
            ("llm", "prompt injection", "injection", "jailbreak", "rag", "ai"),
            _eval_llm,
            active_on_target=True,
        ),
        CheckSpec(
            "agent_tool_abuse",
            "Agent tool-abuse probes",
            "agent_security",
            "agent_probe",
            "high",
            URL,
            frozenset({"ai_app"}),
            "Attempts to push an agent into unintended tool calls; may trigger real actions.",
            ("A reachable target URL source", "Test-only credentials and tools"),
            ("tool-call traces", "pass/fail per probe"),
            ("agent", "tool abuse", "excessive agency"),
            _eval_agent,
            active_on_target=True,
            always_requires_approval=True,
        ),
        CheckSpec(
            "custom_script",
            "Developer-supplied script",
            "custom",
            "custom_script",
            "high",
            CODE,
            _ALL,
            "A script you provide, executed only inside the sandbox.",
            ("An uploaded script artifact",),
            ("script output", "exit code"),
            (),
            _eval_custom,
            always_requires_approval=True,
        ),
    )
}


# ---- recommendation ----------------------------------------------------------------


def _risk_for_target(spec: CheckSpec, target: SourceInfo | None) -> str:
    """Remote targets are shared environments: never below medium, and active checks high."""
    risk = spec.base_risk
    if target is not None and target.source_type == "remote_url":
        risk = max_risk(risk, "medium")
        if spec.active_on_target:
            risk = max_risk(risk, "high")
    return risk


def _definition(
    spec: CheckSpec, target: SourceInfo | None, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    definition: dict[str, Any] = {
        "check_id": spec.check_id,
        "summary": spec.summary,
        "prerequisites": list(spec.prerequisites),
        "expected_evidence": list(spec.expected_evidence),
        "parameters": params or {},
        "target": None,
        "active_on_target": spec.active_on_target,
        "needs_egress": spec.needs_egress,
    }
    if target is not None:
        definition["target"] = {
            "source_id": str(target.id),
            "source_type": target.source_type,
            "name": target.name,
            "environment": target.environment,
        }
    return definition


def _targets_for(spec: CheckSpec, ctx: PlanContext) -> list[SourceInfo | None]:
    if spec.target_kind == URL:
        urls = [s for s in ctx.sources if s.kind == URL]
        return [*urls] if urls else [None]
    if ctx.snapshot_source_id is not None:
        snap = [s for s in ctx.sources if s.id == ctx.snapshot_source_id]
        if snap:
            return [snap[0]]
    code = [s for s in ctx.sources if s.kind == CODE]
    return [*code[:1]] if code else [None]


def _verdict(spec: CheckSpec, ctx: PlanContext, target: SourceInfo | None) -> Verdict:
    if spec.target_kind == CODE and target is None:
        return Verdict(
            "deferred",
            "Needs a code source (ZIP upload or Git repository) registered in the project.",
        )
    return spec.evaluate(ctx, target)


def _proposal(
    spec: CheckSpec,
    ctx: PlanContext,
    target: SourceInfo | None,
    origin: str,
    why: str | None = None,
    params: dict[str, Any] | None = None,
    name: str | None = None,
) -> Proposal:
    verdict = _verdict(spec, ctx, target)
    rationale = verdict.reason if why is None else f"{why} {verdict.reason}"
    label = name or (f"{spec.name} - {target.name}" if target is not None else spec.name)
    return Proposal(
        check_id=spec.check_id,
        name=label[:300],
        category=spec.category,
        tool=spec.tool,
        origin=origin,
        risk_level=_risk_for_target(spec, target),
        status=verdict.status,
        rationale=rationale,
        definition=_definition(spec, target, params),
        source_id=target.id if target else None,
        always_requires_approval=spec.always_requires_approval,
    )


def recommend(ctx: PlanContext) -> list[Proposal]:
    """Automatic mode: every catalog check, each either planned or explained. Pure function
    of the context: the same evidence always gives the same plan, in a stable order."""
    out: list[Proposal] = []
    for spec in CATALOG.values():
        if spec.check_id == "custom_script" or not spec.automatic:  # developer-defined only
            continue
        for target in _targets_for(spec, ctx):
            out.append(_proposal(spec, ctx, target, "recommended"))
    return out[:MAX_TESTS_PER_PLAN]


def match_prompt(prompt: str) -> dict[str, list[str]]:
    """Deterministic keyword selection of catalog checks from free text. The prompt is
    untrusted data: it can only choose among catalog entries, never add commands. Model-based
    interpretation arrives with the LangGraph stage and will go through the same catalog."""
    text = " ".join(prompt.lower().split())
    hits: dict[str, list[str]] = {}
    for spec in CATALOG.values():
        if not spec.automatic:
            continue
        found = [
            k for k in spec.keywords if re.search(rf"(?<![a-z0-9]){re.escape(k)}(?![a-z0-9])", text)
        ]
        if found:
            hits[spec.check_id] = found
    return hits


def from_prompt(ctx: PlanContext, prompt: str) -> list[Proposal]:
    hits = match_prompt(prompt)
    out: list[Proposal] = []
    for spec in CATALOG.values():
        if spec.check_id not in hits:
            continue
        why = f"Selected because the prompt mentions: {', '.join(sorted(hits[spec.check_id]))}."
        for target in _targets_for(spec, ctx):
            out.append(_proposal(spec, ctx, target, "prompt", why=why))
    return out[:MAX_TESTS_PER_PLAN]


# ---- developer-defined tests -------------------------------------------------------


class InvalidTestDefinition(ValueError):
    """The developer-supplied definition is not acceptable (message is safe to return)."""


def _clean_params(spec: CheckSpec, params: dict[str, Any]) -> dict[str, Any]:
    if len(params) > MAX_PARAMS:
        raise InvalidTestDefinition(f"At most {MAX_PARAMS} parameters are allowed")
    clean: dict[str, Any] = {}
    for key, value in params.items():
        if key == "timeout_seconds":
            if not isinstance(value, int) or isinstance(value, bool) or not 10 <= value <= 3600:
                raise InvalidTestDefinition("timeout_seconds must be an integer from 10 to 3600")
            clean[key] = value
        elif key == "target_path" and spec.target_kind == CODE:
            if not isinstance(value, str) or not PATH_PARAM.match(value):
                raise InvalidTestDefinition("target_path must be a relative path inside the source")
            clean[key] = value
        elif key == "url_path" and spec.target_kind == URL:
            if not isinstance(value, str) or not URL_PATH_PARAM.match(value) or ".." in value:
                raise InvalidTestDefinition(
                    "url_path must start with '/' and use plain path characters"
                )
            clean[key] = value
        else:
            raise InvalidTestDefinition(f"Parameter '{key}' is not allowed for {spec.check_id}")
    return clean


def from_developer(
    ctx: PlanContext,
    *,
    check_id: str,
    source_id: uuid.UUID | None,
    name: str | None,
    parameters: dict[str, Any],
    script_artifact_id: uuid.UUID | None,
) -> Proposal:
    spec = CATALOG.get(check_id)
    if spec is None or not spec.developer_selectable:
        raise InvalidTestDefinition("Unknown check_id")
    target: SourceInfo | None = None
    if source_id is not None:
        found = [s for s in ctx.sources if s.id == source_id]
        if not found:  # unknown, inactive or another project's source: indistinguishable
            raise InvalidTestDefinition("source_id is not an active source of this project")
        target = found[0]
        if target.kind != spec.target_kind:
            raise InvalidTestDefinition(
                f"{spec.check_id} needs a {'URL' if spec.target_kind == URL else 'code'} source"
            )
    elif spec.target_kind == URL:
        raise InvalidTestDefinition("source_id is required for checks that need a running target")
    if (spec.check_id == "custom_script") != (script_artifact_id is not None):
        raise InvalidTestDefinition(
            "script_artifact_id is required for custom_script and not allowed for other checks"
        )
    clean = _clean_params(spec, parameters)
    proposal = _proposal(spec, ctx, target, "developer_defined", params=clean, name=name)
    if spec.check_id == "custom_script":
        proposal = Proposal(**{**proposal.__dict__, "script_artifact_id": script_artifact_id})
    return proposal
