"""The only commands a sandbox may run: a fixed, server-side table keyed by catalog check id.

Nothing here comes from a request, a plan parameter or a prompt. Checks that are not listed
have no runner yet and are recorded as skipped (their runners arrive in Stage 9+).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckCommand:
    check_id: str
    argv: tuple[str, ...]
    needs_workspace: bool = True
    needs_network: bool = False


COMMANDS: dict[str, CheckCommand] = {
    # Lists and counts the extracted files; never imports or executes project code.
    "sandbox_smoke": CheckCommand("sandbox_smoke", ("python", "-I", "/opt/sentinel/smoke.py")),
}


def lookup(check_id: str) -> CheckCommand | None:
    return COMMANDS.get(check_id)
