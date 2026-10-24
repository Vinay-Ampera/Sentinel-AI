"""The environment example file documents every Stage 12 setting once, with no secret values.

``ENV_EXAMPLE_PATH`` (default ``backend/.env.example``) lets the same checks run on another file,
for example the ready-made block ``docs/env-stage12.example``. The file is only parsed here:
nothing is read from ``backend/.env``."""

import os
import re
from collections import Counter
from pathlib import Path

import pytest

from sentinel_ai.core.config import Settings

REPO = Path(__file__).resolve().parents[3]
PATH = Path(os.environ.get("ENV_EXAMPLE_PATH") or REPO / "backend" / ".env.example")
STAGE12 = (
    "INGEST_MAX_BODY_KIB", "INGEST_MAX_EVENTS_PER_REQUEST", "INGEST_REQUESTS_PER_MINUTE",
    "INGEST_EVENTS_PER_MINUTE", "INGEST_FAILED_AUTH_PER_MINUTE", "INGEST_KEY_DEFAULT_DAYS",
    "INGEST_KEY_MAX_DAYS", "INGEST_KEYS_PER_PROJECT", "EVENT_DAILY_QUOTA",
    "EVENT_MAX_GROUPS_PER_PROJECT", "EVENT_SAMPLES_PER_GROUP", "EVENT_SAMPLE_RETENTION_DAYS",
    "EVENT_GROUP_RETENTION_DAYS", "ALERT_OPEN_CAP", "RATE_LIMIT_BACKEND", "TRUSTED_PROXY_CIDRS",
    "ALERT_EVALUATION_ENABLED", "ALERT_EVALUATION_INTERVAL_SECONDS", "EVENT_PURGE_ENABLED",
    "EVENT_PURGE_INTERVAL_SECONDS",
)  # fmt: skip
_ASSIGN = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=(.*)$")
_SECRET_NAME = re.compile(r"(PASSWORD|PEPPER|API_KEY|SECRET|TOKEN)")


def assignments() -> list[tuple[str, str, bool]]:
    """(name, value, commented) for every ``NAME=value`` line, commented or not."""
    out = []
    for line in PATH.read_text().splitlines():
        m = _ASSIGN.match(line)
        if m:
            out.append(
                (m.group(1), m.group(2).split("#", 1)[0].strip(), line.lstrip().startswith("#"))
            )
    return out


pytestmark = pytest.mark.skipif(not PATH.exists(), reason=f"{PATH} not found")


def test_no_setting_is_documented_twice() -> None:
    counts = Counter(name for name, _, _ in assignments())
    assert {n: c for n, c in counts.items() if c > 1} == {}


def test_every_stage_12_setting_is_documented() -> None:
    names = {name for name, _, _ in assignments()}
    if PATH.name == ".env.example":
        assert set(STAGE12) <= names, sorted(set(STAGE12) - names)
    else:  # the block file documents exactly the Stage 12 settings
        assert set(STAGE12) == names, (sorted(set(STAGE12) - names), sorted(names - set(STAGE12)))


def test_stage_12_names_are_real_settings() -> None:
    fields = {f.upper() for f in Settings.model_fields}
    unknown = [n for n in STAGE12 if n not in fields]
    assert unknown == []  # a typo in the example would silently do nothing


def test_documented_stage_12_values_load_and_secret_names_hold_no_values() -> None:
    values = {n: v for n, v, _ in assignments() if n in STAGE12 and v}
    from support import make_settings

    parsed = {k.lower(): v for k, v in values.items()}
    make_settings(
        **parsed
    )  # the defaults shown in the file must be accepted by the real validators
    for name, value, commented in assignments():
        if _SECRET_NAME.search(name) and not commented:
            assert value == "", f"{name} must not carry a value in an example file"
