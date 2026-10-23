"""The only commands a sandbox may run: a fixed, server-side table keyed by catalog check id.

Nothing here comes from a request, a prompt or sandbox output. The only variable parts are
plan parameters that were validated when the plan was made and are validated again here
(a relative path for pytest, a timeout). Checks that are not listed have no runner yet and
are recorded as skipped.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

PYTEST_RESULT_FILE = "/tmp/junit.xml"
BANDIT_RESULT_FILE = "/tmp/bandit.json"
SEMGREP_RESULT_FILE = "/tmp/semgrep.json"
DEPS_RESULT_FILE = "/tmp/deps.json"
ZAP_RESULT_FILE = "/workspace/zap.json"
SEMGREP_RULES_DIR = "/opt/sentinel/semgrep-rules"
IMAGE_BASE = "base"  # the sandbox runner image (Python, pytest, Bandit, dependency audit)
IMAGE_SCANNER = "scanner"  # base + the Semgrep binary (compiled, so a separate build)
IMAGE_ZAP = "zap"  # OWASP ZAP; the only image that may be given an egress network
_URL = re.compile(r"https?://[a-z0-9]([a-z0-9.-]{0,251}[a-z0-9])?(:[0-9]{1,5})?")
_URL_PATH = re.compile(r"/(?!/)[A-Za-z0-9_.~%-]*(/[A-Za-z0-9_.~%-]*){0,20}")
_FULL_URL = re.compile(_URL.pattern + _URL_PATH.pattern)
_SAFE_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}")


class InvalidParameters(ValueError):
    """A plan parameter is not acceptable (message is safe to show)."""


def timeout_parameter(params: Mapping[str, Any]) -> int | None:
    value = params.get("timeout_seconds")
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or not 10 <= value <= 3600:
        raise InvalidParameters("timeout_seconds must be an integer from 10 to 3600")
    return value


def _safe_relative_path(value: Any) -> str:
    if not isinstance(value, str) or not _SAFE_PATH.fullmatch(value):
        raise InvalidParameters("target_path must be a plain relative path inside the source")
    if any(part in ("..", "") for part in value.split("/")) or value.startswith("-"):
        raise InvalidParameters("target_path must be a plain relative path inside the source")
    return value


def _pytest_argv(params: Mapping[str, Any]) -> tuple[str, ...]:
    unknown = set(params) - {"target_path", "timeout_seconds"}
    if unknown:
        raise InvalidParameters("unsupported parameter for pytest")
    timeout_parameter(params)
    argv = (
        "python", "-m", "pytest", "-p", "no:cacheprovider", f"--junitxml={PYTEST_RESULT_FILE}",
        "-o", "junit_family=xunit2", "-q", "--color=no", "--tb=short",
    )  # fmt: skip
    if "target_path" in params:
        return (*argv, "--", _safe_relative_path(params["target_path"]))
    return argv


def _bandit_argv(params: Mapping[str, Any]) -> tuple[str, ...]:
    unknown = set(params) - {"timeout_seconds"}
    if unknown:
        raise InvalidParameters("unsupported parameter for bandit")
    timeout_parameter(params)
    # ``-P`` keeps the project's directory off sys.path: Bandit only parses source text and
    # a file named like one of its imports (yaml.py, bandit.py) must never be loaded.
    return (
        "python", "-P", "-m", "bandit", "-r", ".", "-f", "json", "-o", BANDIT_RESULT_FILE,
        "-q", "-x", "./.git,./node_modules,./.venv,./venv",
    )  # fmt: skip


def _semgrep_argv(params: Mapping[str, Any]) -> tuple[str, ...]:
    if set(params) - {"timeout_seconds"}:
        raise InvalidParameters("unsupported parameter for semgrep")
    timeout_parameter(params)
    # Local rules only (no registry, no account), metrics and version check off. The rules are
    # baked into the image; the scan reads source text and never executes the project.
    return (
        "semgrep", "scan", "--config", SEMGREP_RULES_DIR, "--metrics=off",
        "--disable-version-check", "--json", "--output", SEMGREP_RESULT_FILE, "--quiet",
        "--timeout", "10", "--max-target-bytes", "1000000",
        "--exclude", ".git", "--exclude", "node_modules", "--exclude", ".venv",
        "--exclude", "venv", ".",
    )  # fmt: skip


def _deps_argv(params: Mapping[str, Any]) -> tuple[str, ...]:
    if set(params) - {"timeout_seconds"}:
        raise InvalidParameters("unsupported parameter for the dependency audit")
    timeout_parameter(params)
    return ("python", "-I", "/opt/sentinel/dep_audit.py")


def zap_url(base_url: str, params: Mapping[str, Any]) -> str:
    """The one URL a ZAP run may contact: the authorized source's own origin plus a plain path.
    No credentials, query, fragment or option-like value can pass these checks."""
    if not isinstance(base_url, str) or not _URL.fullmatch(base_url.rstrip("/").lower()):
        raise InvalidParameters("the target URL is not a plain http(s) origin")
    path = params.get("url_path", "/")
    if not isinstance(path, str) or not _URL_PATH.fullmatch(path) or ".." in path:
        raise InvalidParameters("url_path must be a plain path starting with '/'")
    return base_url.rstrip("/").lower() + path


def _zap_argv(
    script: str, minutes: tuple[int, int]
) -> Callable[[Mapping[str, Any]], tuple[str, ...]]:
    def build(params: Mapping[str, Any]) -> tuple[str, ...]:
        if set(params) - {"timeout_seconds", "url_path"}:
            raise InvalidParameters("unsupported parameter for ZAP")
        timeout_parameter(params)
        # The URL is appended by the executor after it has resolved and pinned the host
        # (``with_target``); the script writes /zap/wrk/zap.json, which the image links to
        # the /workspace tmpfs.
        return (
            f"/zap/{script}", "-J", "zap.json", "-I", "-m", str(minutes[0]), "-T", str(minutes[1]),
        )  # fmt: skip

    return build


def with_target(argv: tuple[str, ...], url: str) -> tuple[str, ...]:
    """ZAP's ``-t URL`` placed first after the script; ``url`` comes from ``zap_url``."""
    if not _FULL_URL.fullmatch(url) or ".." in url:
        raise InvalidParameters("the target URL is not a plain http(s) URL")
    return (argv[0], "-t", url, *argv[1:])


@dataclass(frozen=True)
class CheckCommand:
    check_id: str
    argv: tuple[str, ...]
    needs_workspace: bool = True
    needs_network: bool = False
    runs_project_code: bool = False  # executes code from the project: needs an explicit opt-in
    result_file: str | None = None  # framed onto stdout by the in-image runner when set
    kind: str = (
        "generic"  # pytest | bandit | semgrep | dependency_audit | zap: parsing + exit codes
    )
    image: str = IMAGE_BASE
    needs_target: bool = False  # an authorized network target (ZAP): the one egress exception
    active: bool = False  # sends attack-style requests (zap_active)
    build: Callable[[Mapping[str, Any]], tuple[str, ...]] | None = None

    def argv_for(self, params: Mapping[str, Any]) -> tuple[str, ...]:
        return self.build(params) if self.build else self.argv


COMMANDS: dict[str, CheckCommand] = {
    # Lists and counts the extracted files; never imports or executes project code.
    "sandbox_smoke": CheckCommand("sandbox_smoke", ("python", "-I", "/opt/sentinel/smoke.py")),
    # The project's own pytest suite, offline, with the vendored pytest only.
    "pytest_unit": CheckCommand(
        "pytest_unit",
        (),
        runs_project_code=True,
        result_file=PYTEST_RESULT_FILE,
        kind="pytest",
        build=_pytest_argv,
    ),  # fmt: skip
    # Static analysis: Bandit parses the project's Python source as text; nothing is imported
    # or executed, so this is not a "project code" check.
    "bandit_static": CheckCommand(
        "bandit_static",
        (),
        result_file=BANDIT_RESULT_FILE,
        kind="bandit",
        build=_bandit_argv,
    ),  # fmt: skip
    # Semgrep: the compiled binary lives in the separate scanner image; rules are local files.
    "semgrep_static": CheckCommand(
        "semgrep_static",
        (),
        result_file=SEMGREP_RESULT_FILE,
        kind="semgrep",
        image=IMAGE_SCANNER,
        build=_semgrep_argv,
    ),  # fmt: skip
    # Offline dependency audit: lockfiles vs the advisory bundle baked into the image.
    "dependency_audit": CheckCommand(
        "dependency_audit",
        (),
        result_file=DEPS_RESULT_FILE,
        kind="dependency_audit",
        build=_deps_argv,
    ),  # fmt: skip
    # OWASP ZAP against one authorized remote development/staging target (see the threat model).
    "zap_baseline": CheckCommand(
        "zap_baseline",
        (),
        needs_workspace=False,
        result_file=ZAP_RESULT_FILE,
        kind="zap",
        image=IMAGE_ZAP,
        needs_target=True,
        build=_zap_argv("zap-baseline.py", (1, 8)),
    ),  # fmt: skip
    "zap_active": CheckCommand(
        "zap_active",
        (),
        needs_workspace=False,
        result_file=ZAP_RESULT_FILE,
        kind="zap",
        image=IMAGE_ZAP,
        needs_target=True,
        active=True,
        build=_zap_argv("zap-full-scan.py", (2, 20)),
    ),  # fmt: skip
}


def lookup(check_id: str) -> CheckCommand | None:
    return COMMANDS.get(check_id)
