"""Deterministic, read-only static analysis of a validated ZIP.

Nothing from the archive is executed, imported, or written to disk. Output separates:
  * ``facts``       - what files/manifests literally show (with evidence paths);
  * ``inferences``  - conclusions drawn from facts, each with confidence and basis;
  * ``gaps``        - evidence that is unavailable and coverage that cannot be claimed.
Output is a pure function of the archive content (sorted, no timestamps), so analysing the
same bytes twice yields identical results.
"""

import json
import re
import tomllib
import zipfile
from collections import Counter
from collections.abc import Iterable
from typing import Any

from sentinel_ai.services.archive import ArchiveEntry, read_member

ANALYZER_VERSION = "1.0.0"
MANIFEST_READ_CAP = 1024 * 1024
MAX_MANIFESTS_PER_KIND = 50
MAX_EXAMPLES = 20

VENDOR_DIRS = frozenset(
    {"node_modules", ".git", ".venv", "venv", "__pycache__", "site-packages", "vendor", ".tox"}
)
LANGUAGES = {
    ".py": "python", ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".java": "java",
    ".kt": "kotlin", ".go": "go", ".rb": "ruby", ".php": "php", ".cs": "csharp",
    ".rs": "rust", ".swift": "swift", ".c": "c", ".h": "c", ".cc": "cpp", ".cpp": "cpp",
    ".hpp": "cpp", ".html": "html", ".css": "css", ".scss": "css", ".sql": "sql",
    ".sh": "shell",
}  # fmt: skip
NATIVE_BINARY_EXT = frozenset({".exe", ".dll", ".so", ".dylib", ".class", ".jar", ".bin", ".o"})
ARCHIVE_EXT = frozenset({".zip", ".tar", ".gz", ".tgz", ".7z", ".rar"})
KEY_FILE = re.compile(r"(^|/)(id_rsa|id_ed25519|[^/]+\.(pem|key|p12|pfx))$", re.I)

TEST_FILE = re.compile(
    r"(^|/)(test_[^/]+\.py|[^/]+_test\.py|[^/]+\.(test|spec)\.[cm]?[jt]sx?|[^/]+_test\.go"
    r"|[^/]+(Test|Tests)\.java|[^/]+_spec\.rb)$"
)
TEST_DIR = {"test", "tests", "__tests__", "spec", "e2e"}
CONFIG_FILES: list[tuple[str, re.Pattern[str]]] = [
    ("docker", re.compile(r"(^|/)Dockerfile[^/]*$")),
    ("docker_compose", re.compile(r"(^|/)(docker-)?compose[^/]*\.ya?ml$|(^|/)docker-compose[^/]*\.ya?ml$")),
    ("ci_github_actions", re.compile(r"^\.github/workflows/[^/]+\.ya?ml$")),
    ("ci_gitlab", re.compile(r"(^|/)\.gitlab-ci\.ya?ml$")),
    ("ci_jenkins", re.compile(r"(^|/)Jenkinsfile$")),
    ("openapi_spec", re.compile(r"(^|/)(openapi|swagger)[^/]*\.(json|ya?ml)$", re.I)),
    ("env_example", re.compile(r"(^|/)\.env\.(example|sample|template)$")),
    ("typescript_config", re.compile(r"(^|/)tsconfig[^/]*\.json$")),
    ("vite_config", re.compile(r"(^|/)vite\.config\.[cm]?[jt]s$")),
    ("pytest_config", re.compile(r"(^|/)(pytest\.ini|tox\.ini|conftest\.py)$")),
    ("e2e_config", re.compile(r"(^|/)(playwright|cypress)\.config\.[cm]?[jt]s$")),
    ("unit_test_config", re.compile(r"(^|/)(jest|vitest)\.config\.[cm]?[jt]s$")),
    ("coverage_config", re.compile(r"(^|/)(\.coveragerc|\.nycrc[^/]*|codecov\.ya?ml)$")),
    ("makefile", re.compile(r"(^|/)Makefile$")),
]  # fmt: skip
LOCKFILES = re.compile(
    r"(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml|poetry\.lock|Pipfile\.lock|"
    r"go\.sum|Gemfile\.lock|composer\.lock|uv\.lock)$"
)

JS_FRAMEWORKS = {
    "react": "react", "vue": "vue", "@angular/core": "angular", "next": "next.js",
    "nuxt": "nuxt", "svelte": "svelte", "express": "express", "fastify": "fastify",
    "@nestjs/core": "nestjs", "koa": "koa", "vite": "vite",
}  # fmt: skip
JS_TEST_TOOLS = {
    "jest": "jest", "vitest": "vitest", "mocha": "mocha", "@playwright/test": "playwright",
    "cypress": "cypress", "jasmine": "jasmine", "supertest": "supertest",
}  # fmt: skip
JS_COVERAGE = {"c8", "nyc", "istanbul", "@vitest/coverage-v8", "@vitest/coverage-istanbul"}
PY_FRAMEWORKS = {
    "fastapi": "fastapi", "flask": "flask", "django": "django", "starlette": "starlette",
    "langchain": "langchain", "langgraph": "langgraph", "llama-index": "llama-index",
    "openai": "openai", "anthropic": "anthropic", "google-generativeai": "google-generativeai",
    "google-genai": "google-genai",
}  # fmt: skip
PY_TEST_TOOLS = {"pytest": "pytest", "nose": "nose", "hypothesis": "hypothesis", "locust": "locust"}
PY_COVERAGE = {"coverage", "pytest-cov"}
OTHER_FRAMEWORK_MARKERS = {  # (manifest kind, substring) -> framework
    ("pom.xml", "spring-boot"): "spring-boot", ("build.gradle", "spring-boot"): "spring-boot",
    ("go.mod", "gin-gonic/gin"): "gin", ("go.mod", "labstack/echo"): "echo",
    ("Gemfile", "rails"): "rails", ("composer.json", "laravel/framework"): "laravel",
}  # fmt: skip
FRONTEND = {"react", "vue", "angular", "next.js", "nuxt", "svelte"}
BACKEND_API = {
    "fastapi", "flask", "django", "starlette", "express", "fastify", "nestjs", "koa",
    "spring-boot", "gin", "echo", "rails", "laravel",
}  # fmt: skip
LLM = {
    "langchain", "langgraph", "llama-index", "openai", "anthropic",
    "google-generativeai", "google-genai",
}  # fmt: skip


def _segments(path: str) -> list[str]:
    return path.split("/")


def _is_vendor(path: str) -> bool:
    return any(seg in VENDOR_DIRS for seg in _segments(path)[:-1])


def _ext(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return ("." + name.rsplit(".", 1)[1].lower()) if "." in name.lstrip(".") else ""


def _py_name(requirement: str) -> str | None:
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else None


class _Evidence:
    """name -> sorted unique evidence strings (``path`` or ``path: dependency``)."""

    def __init__(self) -> None:
        self._items: dict[str, set[str]] = {}

    def add(self, name: str, evidence: str) -> None:
        self._items.setdefault(name, set()).add(evidence)

    def names(self) -> set[str]:
        return set(self._items)

    def as_list(self) -> list[dict[str, Any]]:
        return [
            {"name": n, "evidence": sorted(e)[:MAX_EXAMPLES]}
            for n, e in sorted(self._items.items())
        ]


def analyze(
    zf: zipfile.ZipFile, entries: Iterable[ArchiveEntry], declared_type: str | None = None
) -> dict[str, Any]:
    entries = list(entries)
    files = [e for e in entries if not e.is_dir]
    vendor = [e for e in files if _is_vendor(e.name)]
    source = [e for e in files if not _is_vendor(e.name)]

    lang_files: Counter[str] = Counter()
    lang_bytes: Counter[str] = Counter()
    for e in source:
        lang = LANGUAGES.get(_ext(e.name))
        if lang:
            lang_files[lang] += 1
            lang_bytes[lang] += e.size

    frameworks, test_tools, coverage_tools = _Evidence(), _Evidence(), _Evidence()
    manifests: list[str] = []
    warnings: list[dict[str, str]] = []
    scripts: dict[str, str] = {}
    _scan_manifests(
        zf, source, frameworks, test_tools, coverage_tools, manifests, warnings, scripts
    )

    tests = _test_files(source)
    config: dict[str, list[str]] = {}
    for e in source:
        for kind, pattern in CONFIG_FILES:
            if pattern.search(e.name):
                config.setdefault(kind, []).append(e.name)
    config = {k: sorted(v)[:MAX_EXAMPLES] for k, v in sorted(config.items())}
    lockfiles = sorted(e.name for e in source if LOCKFILES.search(e.name))

    names = [e.name for e in source]
    sensitive = {
        "env_file_present": sorted(n for n in names if re.search(r"(^|/)\.env(\.[^/]*)?$", n)
                                   and not re.search(r"\.(example|sample|template)$", n))[:MAX_EXAMPLES],
        "key_like_files": sorted(n for n in names if KEY_FILE.search(n))[:MAX_EXAMPLES],
    }  # fmt: skip
    if sensitive["env_file_present"] or sensitive["key_like_files"]:
        warnings.append({
            "id": "sensitive_files_in_archive",
            "detail": "Archive contains .env or key-like files; contents were not read or stored.",
        })  # fmt: skip
    ext_counts = Counter(_ext(n) for n in names)
    native = sum(c for x, c in ext_counts.items() if x in NATIVE_BINARY_EXT)
    nested = sum(c for x, c in ext_counts.items() if x in ARCHIVE_EXT)
    if native:
        warnings.append({"id": "native_binaries", "detail": f"{native} compiled/binary files present (not analysed)."})  # fmt: skip
    if nested:
        warnings.append({"id": "nested_archives", "detail": f"{nested} nested archives present (not opened)."})  # fmt: skip

    facts: dict[str, Any] = {
        "archive": {
            "file_count": len(files),
            "directory_count": len(entries) - len(files),
            "total_uncompressed_bytes": sum(e.size for e in files),
            "vendor_files_excluded": len(vendor),
        },
        "languages": [
            {"name": n, "files": lang_files[n], "bytes": lang_bytes[n]}
            for n in sorted(lang_files, key=lambda k: (-lang_bytes[k], k))
        ],
        "frameworks": frameworks.as_list(),
        "test_tools": test_tools.as_list(),
        "coverage_tools": coverage_tools.as_list(),
        "manifests": sorted(manifests)[: MAX_MANIFESTS_PER_KIND * 4],
        "lockfiles": lockfiles[:MAX_EXAMPLES],
        "test_files": {"count": len(tests), "examples": tests[:MAX_EXAMPLES]},
        "package_scripts": dict(sorted(scripts.items())),
        "config_files": config,
        "sensitive_files": sensitive,
    }
    inferences = _inferences(facts, frameworks.names(), declared_type)
    gaps = _gaps(facts, inferences)
    return {
        "schema_version": 1,
        "analyzer_version": ANALYZER_VERSION,
        "method": "static_archive_inspection",
        "executed_code": False,
        "facts": facts,
        "inferences": inferences,
        "gaps": gaps,
        "warnings": sorted(warnings, key=lambda w: w["id"]),
    }


def _test_files(source: list[ArchiveEntry]) -> list[str]:
    found = []
    for e in source:
        segs = _segments(e.name)
        in_test_dir = any(s in TEST_DIR for s in segs[:-1]) and _ext(e.name) in LANGUAGES
        if TEST_FILE.search(e.name) or in_test_dir:
            found.append(e.name)
    return sorted(found)


def _scan_manifests(
    zf: zipfile.ZipFile,
    source: list[ArchiveEntry],
    frameworks: _Evidence,
    test_tools: _Evidence,
    coverage_tools: _Evidence,
    manifests: list[str],
    warnings: list[dict[str, str]],
    scripts: dict[str, str],
) -> None:
    per_kind: Counter[str] = Counter()
    for e in sorted(source, key=lambda x: x.name):
        base = e.name.rsplit("/", 1)[-1]
        kind = "requirements" if re.fullmatch(r"requirements[^/]*\.txt", base) else base
        if kind not in {"package.json", "requirements", "pyproject.toml", "go.mod", "pom.xml",
                        "build.gradle", "Gemfile", "composer.json"}:  # fmt: skip
            continue
        per_kind[kind] += 1
        if per_kind[kind] > MAX_MANIFESTS_PER_KIND:
            continue
        data, truncated = read_member(zf, e.name, MANIFEST_READ_CAP)
        manifests.append(e.name)
        if truncated:
            warnings.append({"id": "manifest_truncated", "detail": f"{e.name} exceeds the read limit; ignored."})  # fmt: skip
            continue
        text = data.decode("utf-8", "replace")
        try:
            if kind == "package.json":
                _package_json(
                    e.name, json.loads(text), frameworks, test_tools, coverage_tools, scripts
                )
            elif kind == "requirements":
                deps = [_py_name(line.split("#")[0]) for line in text.splitlines()
                        if line.strip() and not line.lstrip().startswith(("-", "#"))]  # fmt: skip
                _python_deps(e.name, [d for d in deps if d], frameworks, test_tools, coverage_tools)
            elif kind == "pyproject.toml":
                _pyproject(e.name, tomllib.loads(text), frameworks, test_tools, coverage_tools)
            else:
                for (mk, needle), fw in OTHER_FRAMEWORK_MARKERS.items():
                    if mk == kind and needle in text:
                        frameworks.add(fw, f"{e.name}: {needle}")
        except (ValueError, TypeError, AttributeError):  # json/toml errors are ValueError
            warnings.append({"id": "manifest_unparsable", "detail": f"{e.name} could not be parsed."})  # fmt: skip


def _package_json(
    path: str, doc: Any, fw: _Evidence, tt: _Evidence, cov: _Evidence, scripts: dict[str, str]
) -> None:
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    deps: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = doc.get(key)
        if isinstance(section, dict):
            deps |= {str(k) for k in section}
    for dep in deps:
        if dep in JS_FRAMEWORKS:
            fw.add(JS_FRAMEWORKS[dep], f"{path}: {dep}")
        if dep in JS_TEST_TOOLS:
            tt.add(JS_TEST_TOOLS[dep], f"{path}: {dep}")
        if dep in JS_COVERAGE:
            cov.add(dep, f"{path}: {dep}")
    declared = doc.get("scripts")
    if isinstance(declared, dict):
        for name in ("test", "test:unit", "test:e2e", "lint", "build"):
            if isinstance(declared.get(name), str):
                scripts[f"{path}#{name}"] = declared[name][:200]


def _python_deps(path: str, deps: list[str], fw: _Evidence, tt: _Evidence, cov: _Evidence) -> None:
    for dep in deps:
        if dep in PY_FRAMEWORKS:
            fw.add(PY_FRAMEWORKS[dep], f"{path}: {dep}")
        if dep in PY_TEST_TOOLS:
            tt.add(PY_TEST_TOOLS[dep], f"{path}: {dep}")
        if dep in PY_COVERAGE:
            cov.add(dep, f"{path}: {dep}")


def _pyproject(
    path: str, doc: dict[str, Any], fw: _Evidence, tt: _Evidence, cov: _Evidence
) -> None:
    deps: list[str] = []
    project = doc.get("project", {})
    deps += [d for r in project.get("dependencies", []) if (d := _py_name(str(r)))]
    for group in project.get("optional-dependencies", {}).values():
        deps += [d for r in group if (d := _py_name(str(r)))]
    for group in doc.get("dependency-groups", {}).values():
        deps += [d for r in group if isinstance(r, str) and (d := _py_name(r))]
    poetry = doc.get("tool", {}).get("poetry", {})
    sections = [poetry.get("dependencies", {}), poetry.get("dev-dependencies", {})]
    sections += [g.get("dependencies", {}) for g in poetry.get("group", {}).values()]
    for section in sections:
        deps += [d for k in section if (d := _py_name(str(k)))]
    _python_deps(path, sorted(set(deps)), fw, tt, cov)
    if "pytest" in doc.get("tool", {}) and "pytest" not in tt.names():
        tt.add("pytest", f"{path}: [tool.pytest]")


def _inferences(facts: dict[str, Any], fw: set[str], declared: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    langs = facts["languages"]
    config = facts["config_files"]
    candidates: dict[str, list[str]] = {}
    if fw & FRONTEND:
        candidates["web_app"] = sorted(fw & FRONTEND)
    if (fw & BACKEND_API) or "openapi_spec" in config:
        candidates["rest_api"] = sorted(fw & BACKEND_API) + (
            ["openapi_spec"] if "openapi_spec" in config else []
        )
    if fw & LLM:
        candidates["ai_app"] = sorted(fw & LLM)
    for app_type, basis in sorted(candidates.items()):
        out.append({
            "id": f"application_type:{app_type}",
            "statement": f"Likely a {app_type.replace('_', ' ')}",
            "confidence": "medium",
            "basis": basis,
        })  # fmt: skip
    if declared and candidates and declared not in candidates:
        out.append({
            "id": "declared_type_unsupported",
            "statement": f"Declared application type '{declared}' is not supported by detected evidence",
            "confidence": "low",
            "basis": sorted(candidates),
        })  # fmt: skip
    if langs:
        out.append({
            "id": "primary_language",
            "statement": f"Primary language by size is {langs[0]['name']}",
            "confidence": "high" if len(langs) == 1 else "medium",
            "basis": [f"{langs[0]['files']} files, {langs[0]['bytes']} bytes"],
        })  # fmt: skip
    for key, value in facts["package_scripts"].items():
        if key.endswith("#test"):
            out.append({
                "id": f"test_entrypoint:{key}",
                "statement": f"Tests are probably run with the npm 'test' script ({key.split('#')[0]})",
                "confidence": "low",
                "basis": [f"scripts.test = {value!r}"],
            })  # fmt: skip
    return out


def _gap(gap_id: str, kind: str, what: str, why: str) -> dict[str, str]:
    return {"id": gap_id, "kind": kind, "what": what, "why": why}


def _gaps(facts: dict[str, Any], inferences: list[dict[str, Any]]) -> list[dict[str, str]]:
    gaps = [
        _gap("runtime_behavior", "unavailable_evidence", "Runtime behaviour, test results and coverage",
             "Static analysis only; no project code was executed."),
        _gap("dependency_vulnerabilities", "unavailable_evidence", "Known-vulnerability status of dependencies",
             "No dependency audit has been run."),
    ]  # fmt: skip
    tests, tools = facts["test_files"]["count"], facts["test_tools"]
    config = facts["config_files"]
    if tests == 0:
        gaps.append(_gap("no_tests_detected", "coverage_gap", "Automated tests", "No test files were detected."))  # fmt: skip
    if tests and not (facts["coverage_tools"] or "coverage_config" in config):
        gaps.append(_gap("no_coverage_tooling", "coverage_gap", "Coverage measurement",
                         "Tests exist but no coverage tooling was detected."))  # fmt: skip
    if tests and not tools and not any(i["id"].startswith("test_entrypoint") for i in inferences):
        gaps.append(_gap("test_runner_unknown", "unavailable_evidence", "How tests are run",
                         "Test files exist but no test framework or script was identified."))  # fmt: skip
    if not any(k.startswith("ci_") for k in config):
        gaps.append(_gap("no_ci_config", "coverage_gap", "CI configuration", "No CI configuration was detected."))  # fmt: skip
    ids = {i["id"] for i in inferences}
    if "application_type:rest_api" in ids and "openapi_spec" not in config:
        gaps.append(_gap("no_openapi_spec", "unavailable_evidence", "API contract",
                         "An API is likely but no OpenAPI/Swagger file was found."))  # fmt: skip
    if facts["manifests"] and not facts["lockfiles"]:
        gaps.append(_gap("no_lockfile", "coverage_gap", "Reproducible dependency versions",
                         "Manifests exist but no lockfile was found."))  # fmt: skip
    return sorted(gaps, key=lambda g: g["id"])
