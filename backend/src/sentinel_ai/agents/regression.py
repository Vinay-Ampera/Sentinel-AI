"""Regression-test agent: a drafted test for a reproducible failure, stored for human review.

A draft is *text*. It is never written to the source tree, committed or executed by Sentinel in
Stage 11. Deterministic checks decide whether it is acceptable at all: path rules, size, a
syntax check by parsing (never running) Python, a list of risky constructs shown to the
reviewer, and an overlap check against test names we already know."""

import ast
import hashlib
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sentinel_ai.agents.common import EvidenceId, cites_only, one_line
from sentinel_ai.integrations.llm import evidence_filter as ef
from sentinel_ai.integrations.llm.types import GatewayRequest

TEMPLATE_VERSION = "regression-v1"
EVIDENCE_CHARS = 14_000
MAX_OUTPUT_TOKENS = 1800
MAX_CODE_CHARS = 20_000
# A person sets these on a finding's verification_state; scanners never do.
ELIGIBLE_VERIFICATION_STATES = frozenset({"likely", "confirmed"})
ELIGIBLE_RESULT_STATUSES = frozenset({"failed", "error"})
ALLOWED_SUFFIXES = {
    "pytest": (".py",),
    "jest": (".js", ".jsx", ".ts", ".tsx"),
    "vitest": (".js", ".jsx", ".ts", ".tsx"),
}
_PATH = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_./-]{0,198}$")

SYSTEM = (
    "You draft one automated regression test that would have caught the failure or finding "
    "described in the evidence blocks. Use only that evidence and the project's test framework. "
    "Rules: write a single small, deterministic test file; no network access, no subprocesses, "
    "no file writes outside a temporary directory, no secrets; name the test so its purpose is "
    "clear; cite the evidence ids it is based on; state the expected behaviour. The draft is "
    "reviewed by a person and is not run automatically."
)

_PY_RISKY_IMPORTS = {
    "subprocess",
    "socket",
    "requests",
    "urllib",
    "http",
    "ftplib",
    "smtplib",
    "shutil",
    "ctypes",
    "multiprocessing",
    "pickle",
    "os",
}
_PY_RISKY_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "system",
    "popen",
    "rmtree",
    "remove",
    "unlink",
}
_JS_RISKY = {
    "child_process": r"child_process",
    "filesystem": r"""require\(['"]fs['"]\)|from ['"]fs['"]""",
    "eval": r"\beval\(",
    "network": r"""\bfetch\(|XMLHttpRequest|require\(['"]https?['"]\)""",
}


class RegressionDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    rationale: str = Field(min_length=1, max_length=500)
    target_path: str = Field(min_length=1, max_length=200)
    framework: Literal["pytest", "jest", "vitest"]
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)
    expected_behavior: str = Field(min_length=1, max_length=400)
    evidence_ids: list[EvidenceId] = Field(min_length=1, max_length=6)


def input_hash(subject: str, content_sha: str, model: str | None) -> str:
    return hashlib.sha256(
        "\x1f".join((TEMPLATE_VERSION, model or "", subject, content_sha)).encode()
    ).hexdigest()


def build_request(
    items: list[ef.Excerpt], frameworks: list[str]
) -> tuple[GatewayRequest, ef.EvidenceBlock]:
    block = ef.build_evidence_block("regression", items, max_total_chars=EVIDENCE_CHARS)
    hint = ", ".join(frameworks) if frameworks else "pytest"
    body = (
        f"Detected test tooling: {hint}. Draft the regression test as JSON with keys title, "
        "rationale, target_path (relative, e.g. tests/test_x.py), framework, code, "
        "expected_behavior, evidence_ids.\n\n" + block.text
    )
    request = GatewayRequest(
        purpose="regression",
        template_version=TEMPLATE_VERSION,
        system=ef.with_data_rule(SYSTEM),
        prompt=body,
        output_schema=RegressionDraft,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )
    return request, block


def path_problem(path: str, framework: str) -> str | None:
    if not _PATH.match(path) or ".." in path.split("/") or "//" in path or path.endswith("/"):
        return "target_path must be a plain relative path"
    if not path.endswith(ALLOWED_SUFFIXES[framework]):
        return f"target_path must end with {' or '.join(ALLOWED_SUFFIXES[framework])}"
    return None


def python_facts(code: str) -> tuple[list[str], list[str]] | None:
    """(risk flags, test function names) from parsing only; ``None`` if it is not valid Python."""
    try:
        tree = ast.parse(code)
    except (SyntaxError, ValueError, RecursionError):
        return None
    flags: set[str] = set()
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            flags |= {
                f"import {a.name}" for a in node.names if a.name.split(".")[0] in _PY_RISKY_IMPORTS
            }
        elif (
            isinstance(node, ast.ImportFrom)
            and (node.module or "").split(".")[0] in _PY_RISKY_IMPORTS
        ):
            flags.add(f"import {node.module}")
        elif isinstance(node, ast.Call):
            fn = node.func
            name = (
                fn.id
                if isinstance(fn, ast.Name)
                else fn.attr
                if isinstance(fn, ast.Attribute)
                else ""
            )
            if name in _PY_RISKY_CALLS:
                flags.add(f"call {name}()")
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith(
            "test"
        ):
            names.append(node.name)
    return sorted(flags)[:20], names[:50]


def js_facts(code: str) -> tuple[list[str], list[str]]:
    flags = sorted(label for label, pat in _JS_RISKY.items() if re.search(pat, code))
    names = re.findall(r"""\b(?:it|test)\(\s*['"]([^'"]{1,120})""", code)
    return flags, names[:50]


def validate(
    out: RegressionDraft, shown: set[str], known_test_names: set[str]
) -> tuple[dict[str, Any] | None, str | None]:
    """(clean draft, None) or (None, reason code)."""
    if not cites_only(out.evidence_ids, shown):
        return None, "unknown_evidence"
    problem = path_problem(out.target_path, out.framework)
    if problem:
        return None, "bad_path"
    if "\x00" in out.code:
        return None, "bad_code"
    if out.framework == "pytest":
        facts = python_facts(out.code)
        if facts is None:
            return None, "syntax_error"
        flags, names = facts
    else:
        flags, names = js_facts(out.code)
    overlap = sorted(set(names) & known_test_names)[:10]
    return {
        "title": one_line(out.title, 120),
        "rationale": one_line(out.rationale, 500),
        "expected_behavior": one_line(out.expected_behavior, 400),
        "target_path": out.target_path,
        "framework": out.framework,
        "code": out.code,
        "evidence_ids": list(out.evidence_ids),
        "risk_flags": flags,
        "overlap": overlap,
        "test_names": names[:20],
    }, None
