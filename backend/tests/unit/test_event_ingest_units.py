"""Stage 12 units: fingerprints, event schema, redaction parity, thresholds, key format."""

import uuid
from collections import Counter

import pytest
from pydantic import ValidationError

from sentinel_ai.core.errors import DomainError
from sentinel_ai.core.ratelimit import RateLimiter
from sentinel_ai.integrations.llm.redaction import PromptRedactor
from sentinel_ai.schemas.observability import EventIn
from sentinel_ai.services import event_fingerprint as fp
from sentinel_ai.services import ingestion, observability_policy
from sentinel_ai.services.event_redaction import EventRedactor
from support import make_settings

PID = uuid.UUID("11111111-1111-1111-1111-111111111111")
PY_STACK = (
    "Traceback (most recent call last):\n"
    '  File "/srv/app/main.py", line 10, in handler\n    run()\n'
    '  File "/srv/app/db.py", line 88, in run\n    conn.execute(q)\n'
    "sqlalchemy.exc.OperationalError: connection refused"
)


def key(**kw: object) -> tuple[str, str]:
    base = dict(service="api", environment="staging", level_class="error", error_type="ValueError",
                message="boom", stack=None)  # fmt: skip
    return fp.fingerprint(PID, **{**base, **kw})  # type: ignore[arg-type]


# ---- fingerprints --------------------------------------------------------------------------


def test_volatile_parts_do_not_change_the_fingerprint() -> None:
    a, norm = key(message="User 4821 not found at 10.0.0.7:5432 (req 7f3a9c1d22)")
    b, _ = key(message="User 77 not found at 192.168.1.9:5432 (req aaaaaaaaaa11)")
    assert a == b and "<n>" in norm and "<ip>" in norm


def test_different_errors_services_and_projects_differ() -> None:
    base, _ = key()
    assert key(message="other thing")[0] != base
    assert key(service="worker")[0] != base
    assert key(error_type="KeyError")[0] != base
    assert key(level_class="fatal")[0] != base
    assert fp.fingerprint(uuid.uuid4(), service="api", environment="staging", level_class="error",
                          error_type="ValueError", message="boom", stack=None)[0] != base  # fmt: skip


def test_stack_frames_ignore_line_numbers_and_paths() -> None:
    moved = PY_STACK.replace("line 10", "line 99").replace("/srv/app", "/opt/other/app")
    assert key(stack=PY_STACK)[0] == key(stack=moved)[0]
    assert fp.top_frames(PY_STACK) == ["db.py:run", "main.py:handler"]  # innermost first
    assert key(stack=PY_STACK)[0] != key(stack=None)[0]


def test_node_frames_and_empty_stack() -> None:
    node = "Error: x\n    at handler (/app/src/api.js:12:5)\n    at async main (/app/index.js:3:1)"
    assert fp.top_frames(node) == ["api.js:handler", "index.js:main"]
    assert fp.top_frames(None) == [] and fp.top_frames("no frames here") == []


def test_normalization_is_bounded_and_deterministic() -> None:
    assert len(fp.normalize_message("x" * 5000)) == fp.MAX_MESSAGE_NORM
    assert fp.normalize_message("a   b\n c") == "a b c"
    assert key() == key()
    assert fp.overflow_fingerprint(PID) != fp.overflow_fingerprint(uuid.uuid4())


# ---- event schema --------------------------------------------------------------------------


def ev(**over: object) -> dict[str, object]:
    return {"level": "error", "service": "api", "message": "boom", **over}


def test_a_minimal_event_is_valid_and_defaults_apply() -> None:
    e = EventIn.model_validate(ev())
    assert e.environment == "unknown" and e.attributes == {}


@pytest.mark.parametrize(
    "bad",
    [
        ev(extra_field=1),
        ev(level="loud"),
        ev(service="bad service!"),
        ev(service=""),
        ev(message=""),
        ev(message="x" * 2049),
        ev(stack="x" * 8193),
        ev(trace_id="XYZ"),
        ev(span_id="1234"),
        ev(environment="prod"),
        ev(run_id="not-a-uuid"),
        ev(attributes={"Bad Key": 1}),
        ev(attributes={"k": "v" * 257}),
        ev(attributes={"k": [1]}),
        ev(attributes={f"k{i}": 1 for i in range(21)}),
        ev(attributes={"k": float("inf")}),
        ev(stack="\n".join(f'  File "f.py", line {i}, in g' for i in range(61))),
    ],
)
def test_invalid_events_are_refused(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        EventIn.model_validate(bad)


# ---- redaction -----------------------------------------------------------------------------

SAMPLE = (
    "login failed for ada@example.com password=hunter2hunter2 "
    "Authorization: Bearer abcdefghijklmnop0123 url=postgres://u:pw12345@db/x "
    "key AIza" + "A" * 35
)


def test_event_redaction_matches_the_prompt_redactor_on_shared_patterns() -> None:
    counts: Counter[str] = Counter()
    event_text = EventRedactor().text(SAMPLE, counts)
    prompt_text, report = PromptRedactor().redact(SAMPLE)
    assert event_text == prompt_text  # one pattern set: the two cannot drift
    assert dict(counts) == report.counts
    for secret in ("ada@example.com", "hunter2hunter2", "abcdefghijklmnop0123", "pw12345"):
        assert secret not in event_text


def test_configured_secrets_and_credential_attribute_keys_are_blanked() -> None:
    r = EventRedactor(("super-secret-value-123",))
    counts: Counter[str] = Counter()
    assert "super-secret" not in r.text("see super-secret-value-123 now", counts)
    attrs = r.attributes(
        {"password": "x", "Api_Key": "y", "user": "ada@example.com", "retries": 3, "ok": True},
        counts,
    )
    assert attrs["password"] == attrs["Api_Key"] == "[REDACTED:attribute]"
    assert attrs["retries"] == 3 and attrs["ok"] is True and "ada@" not in attrs["user"]
    assert counts["attribute_key"] == 2


# ---- policy --------------------------------------------------------------------------------


def test_ingest_policy_is_off_unless_explicitly_enabled() -> None:
    assert observability_policy.ingest_enabled({}) is False
    assert (
        observability_policy.ingest_enabled({"observability_ingest": {"enabled": "yes"}}) is False
    )
    assert observability_policy.ingest_enabled({"observability_ingest": {"enabled": True}}) is True
    with pytest.raises(DomainError):
        observability_policy.validate_ingest({"enabled": 1})
    with pytest.raises(DomainError):
        observability_policy.validate_ingest({"enabled": True, "x": 1})


def test_thresholds_are_bounded_and_fall_back_to_defaults() -> None:
    assert observability_policy.validate_thresholds({"new_group_events": 5}) == {
        "new_group_events": 5
    }
    for bad in ({}, {"new_group_events": 0}, {"new_group_events": 101}, {"spike_ratio": 1.0},
                {"unknown": 1}, {"new_group_events": True}, [], {"gap_silence_hours": 500}):  # fmt: skip
        with pytest.raises(DomainError):
            observability_policy.validate_thresholds(bad)
    merged = observability_policy.thresholds({"alert_thresholds": {"spike_ratio": 5}})
    assert merged["spike_ratio"] == 5 and merged["new_group_events"] == 3
    garbage = observability_policy.thresholds({"alert_thresholds": {"spike_ratio": 99999}})
    assert garbage == observability_policy.DEFAULT_THRESHOLDS  # invalid stored value ignored


# ---- keys and limits -----------------------------------------------------------------------


def test_only_well_formed_keys_parse() -> None:
    good = "sai_ing_0123456789ab_" + "x" * 43
    assert ingestion._split(good) == "0123456789ab"
    for bad in ("", "sai_ing_", "sai_ing_0123456789ab", "sai_ing_0123456789AB_x", "sai_ing_zzzzzzzzzzzz_x",
                "other_0123456789ab_x", "sai_ing_0123456789abx_x", "sai_ing_0123456789ab_" + "x" * 300):  # fmt: skip
        assert ingestion._split(bad) is None


def test_key_hash_is_keyed_and_not_the_key() -> None:
    s1, s2 = make_settings(), make_settings(session_token_pepper="another-pepper-" + "y" * 32)
    raw = "sai_ing_0123456789ab_secretsecretsecret"
    assert ingestion._hash(s1, raw) != ingestion._hash(s2, raw)
    assert raw.encode() not in ingestion._hash(s1, raw) and len(ingestion._hash(s1, raw)) == 32


def test_rate_limiter_cost_and_blocked() -> None:
    lim = RateLimiter(5)
    assert lim.allow("k", 3) and not lim.allow("k", 3)  # refused as a whole, nothing recorded
    assert lim.allow("k", 2) and lim.blocked("k") and not lim.allow("k")
    assert not lim.blocked("other")


# ---- hostile input stays cheap ----------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "/" + "a/" * 1000,
        "'" + "x" * 2000,
        '"' * 2048,
        "0123456789abcdef" * 128,
        'File "' * 400,
        "at " + "x (" * 600,
        "a=" * 1000,
        "Bearer " + "A" * 2000,
        "-----BEGIN PRIVATE KEY-----" + "A" * 2000,
        "\x1b[" * 1000,
        ("x" * 31 + " ") * 60,
    ],
)
def test_normalization_and_redaction_run_in_bounded_time(hostile: str) -> None:
    import time

    started = time.perf_counter()
    fp.normalize_message(hostile)
    fp.top_frames(hostile * 4)
    EventRedactor(("configured-secret-value",)).text(hostile * 4, Counter())
    assert time.perf_counter() - started < 0.5


def test_long_key_names_are_still_redacted() -> None:
    text = "the_primary_database_replica_connection_user_account_password=hunter2hunter2 ok"
    out = EventRedactor().text(text, Counter())
    assert "hunter2hunter2" not in out and out.endswith("ok")
    quoted = '{"the_primary_database_replica_connection_user_account_password": "hunter2hunter2"}'
    assert "hunter2hunter2" not in EventRedactor().text(quoted, Counter())
