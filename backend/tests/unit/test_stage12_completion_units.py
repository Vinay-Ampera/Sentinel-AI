"""Stage 12 completion units: client address behind a proxy, OTLP mapping, organization bounds."""

import json

import pytest
from pydantic import ValidationError

from sentinel_ai.core import clientip
from sentinel_ai.core.errors import DomainError
from sentinel_ai.services import observability_policy as op
from sentinel_ai.services import otlp
from support import make_settings

NETS = clientip.parse_networks(["10.0.0.0/8", "192.168.0.0/16"])


# ---- client address ------------------------------------------------------------------------


def test_without_trusted_proxies_the_forwarded_header_is_ignored() -> None:
    assert clientip.client_ip("203.0.113.9", "1.2.3.4", ()) == "203.0.113.9"


def test_a_header_from_an_untrusted_peer_is_ignored() -> None:
    assert clientip.client_ip("198.51.100.7", "1.2.3.4", NETS) == "198.51.100.7"  # spoof attempt


def test_the_right_most_untrusted_hop_is_the_client() -> None:
    assert clientip.client_ip("10.0.0.5", "9.9.9.9, 203.0.113.4, 10.0.0.9", NETS) == "203.0.113.4"
    assert clientip.client_ip("10.0.0.5", "203.0.113.4", NETS) == "203.0.113.4"
    # a client cannot forge a deeper hop: only the part after the last untrusted address counts
    assert clientip.client_ip("10.0.0.5", "1.1.1.1, 203.0.113.4", NETS) == "203.0.113.4"


@pytest.mark.parametrize("header", ["not-an-ip", "203.0.113.4, bogus", "", None])
def test_malformed_or_missing_headers_fall_back_to_the_peer(header: str | None) -> None:
    assert clientip.client_ip("10.0.0.5", header, NETS) == "10.0.0.5"


def test_all_hops_trusted_and_non_ip_peers() -> None:
    assert clientip.client_ip("10.0.0.5", "10.0.0.6, 192.168.1.1", NETS) == "10.0.0.5"
    assert clientip.client_ip("testclient", "1.2.3.4", NETS) is None  # unix sockets, test clients
    assert clientip.client_ip("::1", "1.2.3.4", NETS) == "::1"  # IPv6 peer, IPv4-only trust


def test_trusted_proxy_setting_is_validated() -> None:
    assert make_settings(trusted_proxy_cidrs="10.0.0.0/8, 192.168.0.1").trusted_proxy_cidrs == [
        "10.0.0.0/8", "192.168.0.1",
    ]  # fmt: skip
    assert make_settings().trusted_proxy_cidrs == []  # default: nothing is trusted
    for bad in ("0.0.0.0/0", "::/0", "not a network", "10.0.0.0/8,999.1.1.1"):
        with pytest.raises(ValidationError):
            make_settings(trusted_proxy_cidrs=bad)


# ---- OTLP --------------------------------------------------------------------------------------


def rec(**over: object) -> dict[str, object]:
    return {
        "timeUnixNano": "1761300000000000000",
        "severityNumber": 17,
        "body": {"stringValue": "boom"},
        **over,
    }


def doc(*records: object, resource: list[dict] | None = None) -> dict:
    res = (
        resource
        if resource is not None
        else [{"key": "service.name", "value": {"stringValue": "api"}}]
    )
    return {
        "resourceLogs": [
            {"resource": {"attributes": res}, "scopeLogs": [{"logRecords": list(records)}]}
        ]
    }


@pytest.mark.parametrize(
    ("number", "text", "level"),
    [(1, None, "debug"), (5, None, "debug"), (9, None, "info"), (13, None, "warning"),
     (17, None, "error"), (20, None, "error"), (21, None, "fatal"), (24, None, "fatal"),
     (None, "ERROR", "error"), (None, "warn", "warning"), (None, "CRITICAL", "fatal"),
     (None, None, "info"), (0, "nonsense", "info"), (99, None, "info"), (True, None, "info")],
)  # fmt: skip
def test_severity_mapping_never_promotes_unknown_levels(
    number: object, text: object, level: str
) -> None:
    # OTLP severity numbers 1-4 are "trace": below the floor, the same as debug
    assert otlp.severity_level(number, text) == level


def test_a_record_maps_to_a_native_event() -> None:
    attrs = [
        {"key": "exception.type", "value": {"stringValue": "ValueError"}},
        {"key": "exception.stacktrace", "value": {"stringValue": 'File "a.py", line 1, in f'}},
        {"key": "http.status_code", "value": {"intValue": "500"}},
        {"key": "Retry Count!", "value": {"doubleValue": 2.5}},
        {"key": "ok", "value": {"boolValue": True}},
    ]
    trace = "ab" * 16
    (event,) = otlp.logs_to_events(
        doc(rec(attributes=attrs, traceId=trace, spanId="cd" * 8),
            resource=[{"key": "service.name", "value": {"stringValue": "api"}},
                      {"key": "deployment.environment", "value": {"stringValue": "prod"}},
                      {"key": "service.version", "value": {"stringValue": "1.4.2"}}]), 10)  # fmt: skip
    assert (
        event["level"] == "error"
        and event["service"] == "api"
        and event["environment"] == "production"
    )
    assert event["message"] == "boom" and event["error_type"] == "ValueError"
    assert event["stack"].startswith("File") and event["release"] == "1.4.2"
    assert event["trace_id"] == trace and event["span_id"] == "cd" * 8
    assert event["attributes"] == {"http.status_code": 500, "retry_count_": 2.5, "ok": True}
    assert event["timestamp"].startswith("2025-")


def test_bad_ids_and_values_are_dropped_not_trusted() -> None:
    (event,) = otlp.logs_to_events(
        doc(rec(traceId="0" * 32, spanId="xyz", attributes=[{"key": "a", "value": {"intValue": "nope"}},
                                                          {"key": "b", "value": {"doubleValue": "nan"}},
                                                          {"key": 5, "value": {"stringValue": "x"}}, "junk"])), 10)  # fmt: skip
    assert "trace_id" not in event and "span_id" not in event and "attributes" not in event


def test_body_falls_back_to_the_exception_message_and_structured_bodies_are_text() -> None:
    (a,) = otlp.logs_to_events(doc(rec(body=None, attributes=[{"key": "exception.message", "value": {"stringValue": "it broke"}}])), 5)  # fmt: skip
    assert a["message"] == "it broke"
    (b,) = otlp.logs_to_events(doc(rec(body={"kvlistValue": {"values": [{"key": "k"}]}})), 5)
    assert b["message"].startswith("{")


def test_unknown_service_environment_and_limits() -> None:
    (e,) = otlp.logs_to_events(doc(rec(), resource=[]), 5)
    assert e["service"] == "unknown_service" and e["environment"] == "unknown"
    many = otlp.logs_to_events(doc(*[rec() for _ in range(7)]), 5)
    assert many is not None and len(many) == 6  # limit + 1: the caller refuses the request
    assert (
        otlp.logs_to_events({"resourceLogs": "x"}, 5) is None and otlp.logs_to_events([], 5) is None
    )
    assert otlp.logs_to_events({"resourceLogs": [1, {"scopeLogs": [5, {"logRecords": [None, 3]}]}]}, 5) == [{}, {}]  # fmt: skip
    json.dumps(many)  # JSON-serialisable end to end


# ---- organization bounds ----------------------------------------------------------------------


def test_organization_bounds_can_only_narrow_the_built_in_limits() -> None:
    ok = op.validate_bounds({"new_group_events": {"min": 2, "max": 10}})
    assert ok == {"new_group_events": {"min": 2, "max": 10}}
    for bad in ({}, [], {"nope": {"min": 1, "max": 2}}, {"new_group_events": {"min": 0, "max": 10}},
                {"new_group_events": {"min": 2, "max": 101}}, {"new_group_events": {"min": 9, "max": 3}},
                {"new_group_events": {"min": 1}}, {"new_group_events": {"min": True, "max": 5}},
                {"new_group_events": {"min": 1, "max": 5, "x": 1}}, {"new_group_events": 5}):  # fmt: skip
        with pytest.raises(DomainError):
            op.validate_bounds(bad)


def test_project_thresholds_are_checked_against_the_limits_in_force() -> None:
    bounds = op.effective_bounds(
        {"alert_threshold_bounds": {"new_group_events": {"min": 2, "max": 10}}}
    )
    assert bounds["new_group_events"] == (2, 10) and bounds["spike_ratio"] == (1.5, 20.0)
    assert op.validate_thresholds({"new_group_events": 5}, bounds) == {"new_group_events": 5}
    for value in (1, 11):
        with pytest.raises(DomainError):
            op.validate_thresholds({"new_group_events": value}, bounds)
    assert op.validate_thresholds({"new_group_events": 1}) == {"new_group_events": 1}  # built-in


def test_narrowing_the_bounds_clamps_stored_values_and_garbage_is_ignored() -> None:
    rows = {"alert_thresholds": {"new_group_events": 1, "cost_spike_min_usd": 900}}
    narrowed = {"alert_threshold_bounds": {"new_group_events": {"min": 4, "max": 8},
                                           "cost_spike_min_usd": {"min": 1, "max": 100}}}  # fmt: skip
    got = op.thresholds(rows, narrowed)
    assert got["new_group_events"] == 4 and got["cost_spike_min_usd"] == 100
    assert got["spike_ratio"] == 3.0  # untouched
    assert op.effective_bounds({"alert_threshold_bounds": {"new_group_events": {"min": 0, "max": 5}}}) == op.hard_bounds()  # fmt: skip
    # a default that falls outside narrowed bounds is clamped too
    assert op.thresholds({}, {"alert_threshold_bounds": {"spike_min_events": {"min": 50, "max": 60}}})["spike_min_events"] == 50  # fmt: skip


def test_new_cost_and_resource_thresholds_are_bounded() -> None:
    assert op.validate_thresholds({"cost_spike_ratio": 2.5, "runaway_runs_per_hour": 10, "llm_error_rate_percent": 80, "run_duration_ratio": 4}) == {"cost_spike_ratio": 2.5, "runaway_runs_per_hour": 10, "llm_error_rate_percent": 80, "run_duration_ratio": 4}  # fmt: skip
    for bad in ({"runaway_runs_per_hour": 2}, {"llm_error_rate_percent": 101}, {"cost_spike_min_usd": 0}, {"run_duration_ratio": 1}):  # fmt: skip
        with pytest.raises(DomainError):
            op.validate_thresholds(bad)
