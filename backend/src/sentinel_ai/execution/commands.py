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


@dataclass(frozen=True)
class CheckCommand:
    check_id: str
    argv: tuple[str, ...]
    needs_workspace: bool = True
    needs_network: bool = False
    runs_project_code: bool = False  # executes code from the project: needs an explicit opt-in
    result_file: str | None = None  # framed onto stdout by the in-image runner when set
    kind: str = "generic"  # "pytest" selects result parsing and exit-code mapping
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
}


def lookup(check_id: str) -> CheckCommand | None:
    return COMMANDS.get(check_id)
