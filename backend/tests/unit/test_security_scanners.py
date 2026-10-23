"""Stage 10 unit tests (no Docker, no database, no network): Semgrep, the offline dependency
audit, OWASP ZAP and cross-scanner de-duplication.

Nothing here runs Semgrep, ZAP or a container: reports are fixtures in the formats those tools
document, so these tests prove OUR parsing, command construction, gating and status mapping,
not that the third-party tools behave. See docs/decisions/ADR-0008 for what was verified.
"""

import base64
import hashlib
import importlib.util
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from sentinel_ai.execution import (
    commands,
    dependency_report,
    semgrep_report,
    zap_report,
)
from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import SandboxResult
from sentinel_ai.execution.interface import ExecutionRequest, TargetRef, WorkspaceRef
from sentinel_ai.execution.sandbox_spec import (
    BLACKHOLE_DNS,
    EgressSpec,
    SandboxLimits,
    SandboxSpec,
    create_argv,
)
from sentinel_ai.repositories.findings import GroupCandidate
from sentinel_ai.services import dedup
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip

ROOT = Path(__file__).resolve().parents[3]


def load_script(name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "sandbox" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dep_audit = load_script("dep_audit")
advisories = load_script("advisories")


# ---- Semgrep ------------------------------------------------------------------------------


def sg(path: str = "app/db.py", line: int = 7, rule: str = "opt.sentinel.semgrep-rules.sentinel.python.os-system", **extra: Any) -> dict:  # fmt: skip
    meta = {"cwe": ["CWE-78: Improper Neutralization of Special Elements"], "confidence": "MEDIUM"}
    return {
        "check_id": rule,
        "path": path,
        "start": {"line": line, "col": 1},
        "end": {"line": line, "col": 20},
        "extra": {
            "message": "os.system runs its argument through a shell.",
            "severity": "WARNING",
            "metadata": meta,
            "lines": "os.system(password + 'hunter2')",
            "fingerprint": "requires login",
            **extra,
        },
    }


def sg_report(*results: dict, errors: list | None = None) -> bytes:
    return json.dumps({"version": "1.0", "results": list(results), "errors": errors or [], "paths": {"scanned": ["a.py", "b.py"], "skipped": []}}).encode()  # fmt: skip


def test_semgrep_findings_are_normalized_and_drop_matched_source() -> None:
    parsed = semgrep_report.parse(sg_report(sg()))
    (f,) = parsed.findings
    assert (f.tool, f.rule_id, f.severity, f.confidence, f.path, f.line, f.cwe) == (
        "semgrep", "sentinel.python.os-system", "medium", "medium", "app/db.py", 7, 78,
    )  # fmt: skip
    assert f.category == "static_analysis" and f.fingerprint.startswith("semgrep:")
    stored = __import__("sentinel_ai.execution.scan_report", fromlist=["x"]).sanitized(parsed)
    assert b"hunter2" not in stored and b"os.system(password" not in stored
    assert dict(parsed.extra)["files_scanned"] == 2 and parsed.complete


def test_semgrep_rule_ids_lose_the_rules_directory_prefix() -> None:
    assert semgrep_report.rule_id_of("opt.sentinel.semgrep-rules.sentinel.js.eval") == "sentinel.js.eval"  # fmt: skip
    assert semgrep_report.rule_id_of("sentinel.python.eval-exec") == "sentinel.python.eval-exec"
    assert semgrep_report.rule_id_of("rules.other.thing") == "rules.other.thing"
    assert semgrep_report.rule_id_of("bad id; rm -rf") is None


def test_semgrep_fingerprint_survives_line_moves_and_separates_repeats() -> None:
    a = semgrep_report.parse(sg_report(sg(line=7), sg(line=30))).findings
    b = semgrep_report.parse(sg_report(sg(line=17), sg(line=50))).findings
    assert [f.fingerprint for f in a] == [f.fingerprint for f in b] and a[0].fingerprint != a[1].fingerprint  # fmt: skip


def test_semgrep_hostile_values_are_clamped_and_errors_make_the_scan_incomplete() -> None:
    hostile = sg_report(
        sg(path="/etc/passwd"), sg(path="../x"), sg(line=10**12),
        sg(severity="PANIC", metadata={"confidence": 7, "cwe": "nonsense"}),
        {"check_id": 5}, "junk",
        errors=[{"type": "Syntax error", "long_msg": "x\x00" + "A" * 900}],
    )  # fmt: skip
    parsed = semgrep_report.parse(hostile)
    assert [f.path for f in parsed.findings].count("(unknown)") == 2
    assert all(f.severity in {"low", "medium"} and f.confidence in {"low", "medium"} for f in parsed.findings)  # fmt: skip
    assert len(parsed.errors[0]) <= 200 and "\x00" not in parsed.errors[0] and not parsed.complete


@pytest.mark.parametrize("raw", [b"", b"nope", b"[]", b'{"x": 1}', b'{"results": 5}'])
def test_semgrep_unusable_reports_are_rejected(raw: bytes) -> None:
    with pytest.raises(Exception, match="report"):
        semgrep_report.parse(raw)


def test_semgrep_command_uses_local_rules_only_and_no_plan_option() -> None:
    cmd = commands.lookup("semgrep_static")
    assert cmd and cmd.kind == "semgrep" and cmd.image == commands.IMAGE_SCANNER
    assert not cmd.needs_network and not cmd.runs_project_code and not cmd.needs_target
    argv = cmd.argv_for({"timeout_seconds": 60})
    assert argv[:2] == ("semgrep", "scan") and argv[argv.index("--config") + 1] == "/opt/sentinel/semgrep-rules"  # fmt: skip
    assert "--metrics=off" in argv and "--disable-version-check" in argv
    assert argv[argv.index("--output") + 1] == cmd.result_file == "/tmp/semgrep.json"
    assert not any(a.startswith(("http", "p/", "r/", "auto")) for a in argv)  # no registry config
    for bad in ({"config": "p/ci"}, {"target_path": "x"}, {"timeout_seconds": 5}):
        with pytest.raises(commands.InvalidParameters):
            cmd.argv_for(bad)


def test_the_bundled_semgrep_rules_have_the_required_shape() -> None:
    files = sorted((ROOT / "sandbox" / "semgrep-rules").glob("*.yml"))
    assert files
    ids: set[str] = set()
    for f in files:
        for rule in yaml.safe_load(f.read_text())["rules"]:
            assert rule["id"].startswith("sentinel.") and rule["id"] not in ids
            ids.add(rule["id"])
            assert rule["severity"] in {"ERROR", "WARNING", "INFO"} and rule["languages"]
            assert rule["message"] and rule["metadata"]["cwe"] and rule["metadata"]["confidence"] in {"LOW", "MEDIUM", "HIGH"}  # fmt: skip
            assert any(k in rule for k in ("pattern", "patterns", "pattern-either"))


# ---- dependency audit: advisory data, the in-sandbox script, the host parser ----------------


def osv(id_: str, name: str, events: list[dict], eco: str = "PyPI", **extra: Any) -> dict:
    return {
        "id": id_, "aliases": ["CVE-2024-0001"], "summary": "Bad thing\nin parser",
        "database_specific": {"severity": "HIGH", "cwe_ids": ["CWE-79"]},
        "affected": [{"package": {"ecosystem": eco, "name": name}, "ranges": [{"type": "ECOSYSTEM", "events": events}]}],
        **extra,
    }  # fmt: skip


def bundle(eco: str, *records: dict) -> dict:
    packages: dict[str, list] = {}
    for r in records:
        for k, v in advisories.compact(r, eco).items():
            packages.setdefault(k, []).extend(v)
    return {"schema": 1, "ecosystem": eco, "fetched_at": "2026-10-01T00:00:00Z", "source": "test", "advisory_count": len(records), "packages": packages}  # fmt: skip


def test_advisory_records_are_compacted_normalized_and_filtered() -> None:
    rec = osv(
        "GHSA-aaaa-bbbb-cccc", "Django_Rest.Framework", [{"introduced": "0"}, {"fixed": "3.1"}]
    )
    out = advisories.compact(rec, "PyPI")
    adv = out["django-rest-framework"][0]
    assert adv["severity"] == "high" and adv["cwes"] == [79] and adv["fixed"] == ["3.1"]
    assert adv["summary"] == "Bad thing in parser"
    assert advisories.compact(rec, "npm") == {}  # other ecosystem
    assert advisories.compact({**rec, "withdrawn": "2024-01-01"}, "PyPI") == {}
    git_only = osv("X-1", "pkg", [])
    git_only["affected"][0]["ranges"] = [{"type": "GIT", "events": [{"introduced": "0"}]}]
    assert advisories.compact(git_only, "PyPI") == {}  # cannot match a published version


@pytest.mark.parametrize(
    ("eco", "version", "events", "expected"),
    [
        ("PyPI", "1.5", [{"introduced": "0"}, {"fixed": "2.0"}], True),
        ("PyPI", "2.0", [{"introduced": "0"}, {"fixed": "2.0"}], False),
        ("PyPI", "1.0rc1", [{"introduced": "1.0"}, {"fixed": "1.1"}], False),  # before 1.0
        ("PyPI", "0.9", [{"introduced": "1.0"}], False),
        ("PyPI", "2.4.1", [{"introduced": "2.0"}, {"last_affected": "2.4.1"}], True),
        ("PyPI", "2.4.2", [{"introduced": "2.0"}, {"last_affected": "2.4.1"}], False),
        ("npm", "4.17.20", [{"introduced": "0"}, {"fixed": "4.17.21"}], True),
        ("npm", "4.17.21", [{"introduced": "0"}, {"fixed": "4.17.21"}], False),
        ("npm", "2.0.0-beta.1", [{"introduced": "0"}, {"fixed": "2.0.0"}], True),
        ("npm", "10.0.0", [{"introduced": "9.0.0"}, {"fixed": "9.5.0"}], False),  # not string order
        ("PyPI", "not a version", [{"introduced": "0"}], None),
    ],
)  # fmt: skip
def test_version_ranges_follow_osv_semantics(eco: str, version: str, events: list, expected: object) -> None:  # fmt: skip
    assert dep_audit.in_range(eco, version, events) is expected


def write_project(root: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(body)


POETRY = '[[package]]\nname = "Django"\nversion = "3.0.0"\n\n[[package]]\nname = "safe"\nversion = "9.9"\n'
NPM_LOCK = json.dumps({"lockfileVersion": 3, "packages": {"": {"name": "app"}, "node_modules/lodash": {"version": "4.17.20"}, "node_modules/a/node_modules/@scope/pkg": {"version": "1.0.0"}}})  # fmt: skip


def test_the_in_sandbox_audit_reads_lockfiles_as_data_and_matches_advisories(tmp_path: Path) -> None:  # fmt: skip
    write_project(tmp_path, {
        "poetry.lock": POETRY,
        "api/requirements.txt": "Django==3.0.0  # pinned\nflask>=2\n-r other.txt\nrequests[security]==2.0 ; python_version>'3'\n",
        "web/package-lock.json": NPM_LOCK,
        "yarn.lock": "# yarn lockfile v1\n",
        "node_modules/x/package-lock.json": NPM_LOCK,  # vendored copy: skipped
    })  # fmt: skip
    bundles = {
        "PyPI": bundle("PyPI", osv("PYSEC-1", "django", [{"introduced": "0"}, {"fixed": "3.0.1"}])),
        "npm": bundle(
            "npm",
            osv("GHSA-npm1", "lodash", [{"introduced": "0"}, {"fixed": "4.17.21"}], eco="npm"),
        ),  # fmt: skip
    }
    report = dep_audit.audit(str(tmp_path), bundles)
    assert report["unsupported_lockfiles"] == ["yarn.lock"]
    assert sorted(report["lockfiles"]) == ["api/requirements.txt", "poetry.lock", "web/package-lock.json"]  # fmt: skip
    hits = sorted((r["lockfile"], r["package"], r["advisory_id"]) for r in report["results"])
    assert hits == [
        ("api/requirements.txt", "Django", "PYSEC-1"),
        ("poetry.lock", "Django", "PYSEC-1"),
        ("web/package-lock.json", "lodash", "GHSA-npm1"),
    ]
    assert report["packages_checked"] == 2 + 2 + 2  # poetry, requirements (2 pinned), npm (2)


def test_a_lockfile_that_cannot_be_parsed_is_reported_not_skipped_silently(tmp_path: Path) -> None:  # fmt: skip
    write_project(tmp_path, {"poetry.lock": "this is [not toml", "package-lock.json": "{"})
    report = dep_audit.audit(str(tmp_path), {"PyPI": bundle("PyPI")})
    assert len(report["errors"]) == 2 and report["results"] == []


def test_the_audit_script_refuses_to_run_without_advisory_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # fmt: skip
    monkeypatch.setattr(dep_audit, "ADVISORIES", str(tmp_path / "none"))
    assert dep_audit.main() == 3


def deps_report(*results: dict, lockfiles: list | None = None, unsupported: list | None = None, errors: list | None = None) -> bytes:  # fmt: skip
    return json.dumps({
        "tool": "dependency_audit", "advisory_data": {"PyPI": {"fetched_at": "2026-10-01T00:00:00Z"}},
        "lockfiles": ["poetry.lock"] if lockfiles is None else lockfiles,
        "unsupported_lockfiles": unsupported or [], "packages_checked": 12,
        "results": list(results), "errors": errors or [],
    }).encode()  # fmt: skip


def dep(**over: Any) -> dict:
    return {"ecosystem": "PyPI", "package": "Django", "version": "3.0.0", "lockfile": "poetry.lock", "advisory_id": "PYSEC-1", "aliases": ["CVE-2024-0001", "GHSA-aaaa-bbbb-cccc"], "summary": "Bad thing", "severity": "high", "fixed": ["3.0.1"], "cwes": [79], **over}  # fmt: skip


def test_dependency_findings_are_deduplicated_per_package_version_advisory() -> None:
    parsed = dependency_report.parse(deps_report(dep(), dep(lockfile="api/requirements.txt"), dep(package="django", advisory_id="PYSEC-2", aliases=[])))  # fmt: skip
    assert len(parsed.findings) == 2  # the same pin in two lockfiles is one finding
    f = next(f for f in parsed.findings if f.rule_id == "PYSEC-1")
    assert f.path == "api/requirements.txt" and "Also pinned in: poetry.lock" in f.message
    assert (f.category, f.component, f.severity, f.confidence, f.cwe) == ("dependency", "pypi:Django@3.0.0", "high", "high", 79)  # fmt: skip
    assert f.aliases == ("PYSEC-1", "CVE-2024-0001", "GHSA-aaaa-bbbb-cccc") and f.line is None
    assert "Fixed in: 3.0.1" in f.message
    assert "reachab" in dependency_report.LIMITATIONS.lower()


def test_unsupported_lockfiles_make_the_audit_incomplete() -> None:
    parsed = dependency_report.parse(deps_report(unsupported=["yarn.lock"]))
    assert not parsed.complete and "yarn.lock" in parsed.errors[0]


def test_dependency_report_rejects_hostile_values() -> None:
    parsed = dependency_report.parse(deps_report(dep(package="x; rm -rf /"), dep(version="1 2"), dep(advisory_id="a b"), dep(ecosystem="Maven"), dep(severity="apocalyptic"), "junk"))  # fmt: skip
    assert len(parsed.findings) == 1 and parsed.findings[0].severity == "medium"
    with pytest.raises(Exception, match="report"):
        dependency_report.parse(b'{"tool": "bandit", "results": []}')


# ---- ZAP -------------------------------------------------------------------------------------


def alert(ref: str = "10038-1", name: str = "Content Security Policy Header Not Set", risk: str = "2", conf: str = "3", instances: list | None = None, **extra: Any) -> dict:  # fmt: skip
    return {
        "pluginid": ref.split("-")[0], "alertRef": ref, "alert": name, "name": name,
        "riskcode": risk, "confidence": conf, "cweid": "693",
        "desc": "<p>CSP is an added layer &amp; helps.</p>", "solution": "<p>Set the header.</p>",
        "instances": instances if instances is not None else [
            {"uri": "https://app.example.com/login?token=SECRET#frag", "method": "GET", "param": "", "evidence": "Set-Cookie: session=abc123", "attack": "<script>"},  # fmt: skip
        ],
        **extra,
    }  # fmt: skip


def zap(*alerts: dict, host: str = "app.example.com") -> bytes:
    return json.dumps({"@programName": "ZAP", "site": [{"@name": f"https://{host}", "@host": host, "alerts": list(alerts)}]}).encode()  # fmt: skip


def test_zap_alerts_are_normalized_without_evidence_attacks_or_query_strings() -> None:
    parsed = zap_report.parse(zap(alert()), host="app.example.com")
    (f,) = parsed.findings
    assert (f.tool, f.rule_id, f.severity, f.confidence, f.cwe, f.category) == ("zap", "10038-1", "medium", "high", 693, "dynamic")  # fmt: skip
    assert f.component == "GET https://app.example.com/login" and f.path == "/login"
    assert (
        "<p>" not in f.message and "&amp;" not in f.message and "Fix: Set the header." in f.message
    )
    stored = __import__("sentinel_ai.execution.scan_report", fromlist=["x"]).sanitized(parsed)
    for secret in (b"SECRET", b"abc123", b"<script>"):
        assert secret not in stored
    assert not parsed.complete  # a dynamic scan can never prove a finding is gone
    assert "no attack payloads" in parsed.limitations
    assert "attack-style" in zap_report.parse(zap(alert()), host="app.example.com", active=True).limitations  # fmt: skip


def test_zap_ignores_instances_outside_the_authorized_host() -> None:
    other = {"uri": "https://evil.example.net/x", "method": "GET"}
    mine = {"uri": "https://app.example.com/a", "method": "GET"}
    parsed = zap_report.parse(zap(alert(instances=[other, mine, {"uri": "ftp://app.example.com/z"}])), host="app.example.com")  # fmt: skip
    assert [f.path for f in parsed.findings] == ["/a"]
    assert "outside the authorized host" in parsed.errors[0]


def test_zap_dedupes_instances_and_bounds_hostile_input() -> None:
    inst = {"uri": "https://app.example.com/a?x=1", "method": "GET"}
    parsed = zap_report.parse(zap(alert(instances=[inst, {**inst, "uri": "https://app.example.com/a?x=2"}])), host="app.example.com")  # fmt: skip
    assert len(parsed.findings) == 1
    many = [{"uri": f"https://app.example.com/p{i}", "method": "GET"} for i in range(100)]
    assert len(zap_report.parse(zap(alert(instances=many)), host="app.example.com").findings) == zap_report.MAX_INSTANCES_PER_ALERT  # fmt: skip
    hostile = zap(alert(ref="x y"), alert(name=""), alert(risk="99", conf="-1"), alert(instances=[{"uri": 5}, "junk", {"uri": "https://app.example.com/%00\x00", "method": "TRACE"}]))  # fmt: skip
    assert len(zap_report.parse(hostile, host="app.example.com").findings) <= 3
    with pytest.raises(Exception, match="report"):
        zap_report.parse(b'{"nope": 1}', host="app.example.com")


@pytest.mark.parametrize("params", [{}, {"url_path": "/app/v1"}, {"url_path": "/", "timeout_seconds": 60}])  # fmt: skip
def test_zap_commands_build_one_validated_url(params: dict) -> None:
    for check, script in (("zap_baseline", "zap-baseline.py"), ("zap_active", "zap-full-scan.py")):
        cmd = commands.lookup(check)
        assert cmd and cmd.needs_target and not cmd.needs_workspace and cmd.image == commands.IMAGE_ZAP  # fmt: skip
        url = commands.zap_url("https://App.Example.com:8443/", params)
        argv = commands.with_target(cmd.argv_for(params), url)
        assert argv[:3] == (f"/zap/{script}", "-t", url) and url.startswith("https://app.example.com:8443/")  # fmt: skip
        assert not any(a.startswith("-") and a not in {"-t", "-J", "-I", "-m", "-T"} for a in argv)


@pytest.mark.parametrize("path", ["/a?x=1", "/a#f", "//evil.com", "/../etc", "a", "/a b", "/a;b", "/-x/\x00"])  # fmt: skip
def test_zap_url_paths_cannot_smuggle_anything(path: str) -> None:
    with pytest.raises(commands.InvalidParameters):
        commands.zap_url("https://app.example.com", {"url_path": path})


@pytest.mark.parametrize("base", ["ftp://a.example.com", "https://user:pw@a.example.com", "https://a.example.com/x?y=1", "https://-a.example.com", "javascript:alert(1)", "https://a.example.com -j"])  # fmt: skip
def test_zap_base_urls_must_be_plain_origins(base: str) -> None:
    with pytest.raises(commands.InvalidParameters):
        commands.zap_url(base, {})


@pytest.mark.parametrize("params", [{"url_path": "/x", "scan_policy": "all"}, {"args": "-z"}, {"timeout_seconds": 3}])  # fmt: skip
def test_zap_accepts_no_scanner_option_from_a_plan(params: dict) -> None:
    for check in ("zap_baseline", "zap_active"):
        cmd = commands.lookup(check)
        assert cmd
        with pytest.raises(commands.InvalidParameters):
            cmd.argv_for(params)


# ---- the sandbox spec: network none unless a validated egress is given -----------------------

LIMITS = SandboxLimits(1, 512, 128, 64, 16, 60, 32, 8, 100, 1 << 20, 1 << 20)


def spec(**over: Any) -> SandboxSpec:
    base = dict(image="img:1", scope="s", run_id=uuid.uuid4(), batch_id=uuid.uuid4(), command=("x",), limits=LIMITS, extract_source=False)  # fmt: skip
    return SandboxSpec(**{**base, **over})


def test_network_is_none_unless_a_validated_egress_is_attached() -> None:
    argv = create_argv("docker", "n", spec())
    assert argv[argv.index("--network") + 1] == "none" and "--add-host" not in argv
    egress = EgressSpec("zapnet", "app.example.com", "93.184.216.34")
    argv = create_argv("docker", "n", spec(egress=egress))
    assert argv[argv.index("--network") + 1] == "zapnet"
    assert argv[argv.index("--add-host") + 1] == "app.example.com:93.184.216.34"
    assert argv[argv.index("--dns") + 1] == BLACKHOLE_DNS
    for forbidden in ("--privileged", "--volume", "-v", "--device", "--publish", "-p", "--env", "-e", "--network=host"):  # fmt: skip
        assert forbidden not in argv
    assert argv.count("--network") == 1 and "--cap-drop" in argv and "--read-only" in argv


@pytest.mark.parametrize("egress", [
    EgressSpec("host", "app.example.com", "93.184.216.34"),
    EgressSpec("bridge", "app.example.com", "93.184.216.34"),
    EgressSpec("zapnet", "app.example.com", "10.0.0.5"),
    EgressSpec("zapnet", "app.example.com", "127.0.0.1"),
    EgressSpec("zapnet", "app.example.com", "169.254.169.254"),
    EgressSpec("zapnet", "app.example.com --privileged", "93.184.216.34"),
    EgressSpec("zapnet", "app.example.com", "not-an-ip"),
])  # fmt: skip
def test_unsafe_egress_specs_are_refused(egress: EgressSpec) -> None:
    with pytest.raises(ValueError):
        create_argv("docker", "n", spec(egress=egress))


# ---- the executor with a fake runner ---------------------------------------------------------


class FakeRunner:
    def __init__(self, produce: Callable[[SandboxSpec], SandboxResult], labels: dict[str, str] | None = None) -> None:  # fmt: skip
        self.produce, self.labels, self.specs = produce, labels or {}, []  # type: ignore[var-annotated]

    def run(self, spec: SandboxSpec, stdin: bytes | None, should_stop: object) -> SandboxResult:
        self.specs.append(spec)
        return self.produce(spec)

    def image_label(self, _image: str, label: str) -> str | None:
        return self.labels.get(label)

    def cleanup_batch(self, _b: uuid.UUID) -> bool:
        return True

    def sweep(self, _a: float) -> int:
        return 0


def framed(raw: bytes | None, spec: SandboxSpec, code: int, **extra: Any) -> SandboxResult:
    out = b""
    if raw is not None:
        n = spec.result_nonce
        out = f"\n@@SENTINEL-RESULT {n} {len(raw)} {hashlib.sha256(raw).hexdigest()}\n".encode() + base64.b64encode(raw) + f"\n@@SENTINEL-END {n}\n".encode()  # fmt: skip
    return SandboxResult(started=True, exit_code=code, stdout=out, stdout_tail=out, stderr=b"", **extra)  # fmt: skip


def make_executor(tmp_path: Path, raw: bytes | None, code: int, *, labels: dict[str, str] | None = None, resolver: Callable[[str], list[str]] | None = None, **settings: Any) -> tuple[DockerSandboxExecutor, FakeRunner, WorkspaceRef]:  # fmt: skip
    s = make_settings(artifact_storage_dir=tmp_path, job_executor="docker", **settings)
    runner = FakeRunner(lambda sp: framed(raw, sp, code), labels)
    data = make_zip({"app.py": "x = 1\n"})
    key = f"projects/{uuid.uuid4()}/uploads/a.zip"
    store = ArtifactStore(tmp_path)
    store.path_for(key).parent.mkdir(parents=True)
    store.path_for(key).write_bytes(data)
    ex = DockerSandboxExecutor(s, runner, resolver)  # type: ignore[arg-type]
    return ex, runner, WorkspaceRef(key, sha256_bytes(data), len(data))


def request(check: str, ref: WorkspaceRef | None = None, target: TargetRef | None = None, params: dict | None = None) -> ExecutionRequest:  # fmt: skip
    return ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), check, 1, 600, uuid.uuid4(), ref, params or {}, target)  # fmt: skip


def test_semgrep_runs_in_the_scanner_image_and_maps_status_from_exit_and_report(tmp_path: Path) -> None:  # fmt: skip
    ex, runner, ref = make_executor(tmp_path, sg_report(sg()), 0, sandbox_scanner_image="scanner:1")
    out = ex.execute(request("semgrep_static", ref), lambda: False)
    assert out.status == "failed" and "1 issue" in out.summary and "unverified" in out.summary
    assert runner.specs[0].image == "scanner:1" and runner.specs[0].egress is None
    assert out.scan and out.scan.tool == "semgrep" and out.scan.complete and "bundled rule set" in out.scan.limitations  # fmt: skip
    assert {e.name for e in out.evidence} == {"stdout.log", "stderr.log", "manifest.json", "semgrep.json"}  # fmt: skip
    assert not any(b"hunter2" in e.data for e in out.evidence)
    for code, raw, status in [(0, sg_report(), "passed"), (0, None, "error"), (0, b"junk", "error"), (2, sg_report(), "error"), (7, sg_report(), "error")]:  # fmt: skip
        ex, _, ref = make_executor(tmp_path, raw, code)
        res = ex.execute(request("semgrep_static", ref), lambda: False)
        assert res.status == status, (code, res)
        assert (res.scan is not None) == (status == "passed")  # a failed scan never reads as clean


def test_semgrep_parse_problems_never_make_a_clean_pass(tmp_path: Path) -> None:
    ex, _, ref = make_executor(tmp_path, sg_report(errors=[{"type": "Syntax error", "long_msg": "bad file"}]), 0)  # fmt: skip
    out = ex.execute(request("semgrep_static", ref), lambda: False)
    assert out.status == "error" and out.scan is None
    ex, _, ref = make_executor(tmp_path, sg_report(sg(), errors=[{"type": "Timeout"}]), 0)
    out = ex.execute(request("semgrep_static", ref), lambda: False)
    assert out.status == "failed" and out.scan and not out.scan.complete


def fresh() -> dict[str, str]:
    from datetime import UTC, datetime

    return {"sentinel.advisories.fetched_at": datetime.now(UTC).isoformat()}


def test_dependency_audit_refuses_stale_or_undated_advisory_data(tmp_path: Path) -> None:
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=45)).isoformat()
    for labels, text in [({}, "no advisory data date"), ({"sentinel.advisories.fetched_at": old}, "45 days old"), ({"sentinel.advisories.fetched_at": "garbage"}, "no advisory data date"), ({"sentinel.advisories.fetched_at": "2026-01-01T00:00:00"}, "no advisory data date")]:  # fmt: skip
        ex, runner, ref = make_executor(tmp_path, deps_report(), 0, labels=labels)
        out = ex.execute(request("dependency_audit", ref), lambda: False)
        assert out.status == "blocked" and text in out.summary and runner.specs == []


def test_dependency_audit_results_and_statuses(tmp_path: Path) -> None:
    ex, runner, ref = make_executor(tmp_path, deps_report(dep()), 0, labels=fresh())
    out = ex.execute(request("dependency_audit", ref), lambda: False)
    assert out.status == "failed" and out.scan and out.scan.tool == "dependency_audit"
    assert runner.specs[0].image == "sentinel-sandbox-runner:stage8" and runner.specs[0].egress is None  # fmt: skip
    assert runner.specs[0].command == ("python", "-I", "/opt/sentinel/dep_audit.py")
    assert out.scan.findings[0].category == "dependency" and out.scan.complete
    assert "dependency_audit.json" in {e.name for e in out.evidence}
    manifest = json.loads(next(e for e in out.evidence if e.name == "manifest.json").data)
    assert manifest["advisory_data_fetched_at"] and manifest["network"] == "none"
    for code, raw, status in [(0, deps_report(), "passed"), (0, deps_report(lockfiles=[]), "skipped"), (3, None, "error"), (0, None, "error"), (1, deps_report(), "error"), (0, deps_report(unsupported=["yarn.lock"]), "error")]:  # fmt: skip
        ex, _, ref = make_executor(tmp_path, raw, code, labels=fresh())
        res = ex.execute(request("dependency_audit", ref), lambda: False)
        assert res.status == status, (code, res)
    ex, _, ref = make_executor(tmp_path, deps_report(dep(), unsupported=["yarn.lock"]), 0, labels=fresh())  # fmt: skip
    out = ex.execute(request("dependency_audit", ref), lambda: False)
    assert out.status == "failed" and out.scan and not out.scan.complete  # cannot verify fixes


TARGET = TargetRef("https://app.example.com", "staging", uuid.uuid4())
ZAP_ON = dict(sandbox_zap_image="zap-runner:1", sandbox_zap_network="zapnet", sandbox_zap_egress_attested=True)  # fmt: skip
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731


def test_zap_is_blocked_unless_the_operator_enabled_and_attested_it(tmp_path: Path) -> None:
    for settings in ({}, dict(ZAP_ON, sandbox_zap_egress_attested=False), {k: v for k, v in ZAP_ON.items() if k != "sandbox_zap_network"}):  # fmt: skip
        ex, runner, _ = make_executor(tmp_path, zap(), 0, resolver=PUBLIC, **settings)
        out = ex.execute(request("zap_baseline", None, TARGET), lambda: False)
        assert out.status == "blocked" and "not enabled" in out.summary and runner.specs == []


@pytest.mark.parametrize(
    ("target", "resolver", "text"),
    [
        (None, PUBLIC, "no authorized target"),
        (TargetRef("https://app.example.com", "production", uuid.uuid4()), PUBLIC, "development or staging"),  # fmt: skip
        (TargetRef("https://app.example.com", "staging", uuid.uuid4()), lambda h: [], "could not be resolved"),  # fmt: skip
        (TargetRef("https://app.example.com", "staging", uuid.uuid4()), lambda h: ["93.184.216.34", "10.0.0.8"], "non-public"),  # fmt: skip
        (TargetRef("https://app.example.com", "staging", uuid.uuid4()), lambda h: ["169.254.169.254"], "non-public"),  # fmt: skip
        (TargetRef("https://app.example.com", "staging", uuid.uuid4()), lambda h: ["127.0.0.1"], "non-public"),  # fmt: skip
        (TargetRef("https://localhost:3000", "staging", uuid.uuid4()), PUBLIC, "Blocked"),
        (TargetRef("https://93.184.216.34", "staging", uuid.uuid4()), PUBLIC, "DNS name"),
        (TargetRef("https://intranet.corp", "staging", uuid.uuid4()), PUBLIC, "Blocked"),
        (TargetRef("https://app.example.com/?x=1", "staging", uuid.uuid4()), PUBLIC, "Blocked"),
    ],
)  # fmt: skip
def test_zap_refuses_before_any_container_starts(tmp_path: Path, target: TargetRef | None, resolver: Callable, text: str) -> None:  # fmt: skip
    ex, runner, _ = make_executor(tmp_path, zap(), 0, resolver=resolver, **ZAP_ON)
    out = ex.execute(request("zap_baseline", None, target), lambda: False)
    assert out.status == "blocked" and text in out.summary and runner.specs == []


def test_zap_runs_with_a_pinned_target_and_records_the_network(tmp_path: Path) -> None:
    ex, runner, _ = make_executor(tmp_path, zap(alert()), 0, resolver=PUBLIC, **ZAP_ON)
    out = ex.execute(request("zap_baseline", None, TARGET, {"url_path": "/app"}), lambda: False)
    assert out.status == "failed" and out.scan and out.scan.tool == "zap" and not out.scan.complete
    sp = runner.specs[0]
    assert sp.image == "zap-runner:1" and sp.extract_source is False
    assert sp.egress == EgressSpec("zapnet", "app.example.com", "93.184.216.34")
    assert sp.command[:3] == ("/zap/zap-baseline.py", "-t", "https://app.example.com/app")
    assert sp.limits.memory_mb == 2048 and sp.limits.timeout_seconds == 600  # min(request, zap)
    manifest = json.loads(next(e for e in out.evidence if e.name == "manifest.json").data)
    assert manifest["network"] == {"name": "zapnet", "host": "app.example.com", "pinned_ip": "93.184.216.34", "dns": "black hole (only the pinned host resolves)"}  # fmt: skip
    assert manifest["target_url"] == "https://app.example.com/app"
    argv = create_argv("docker", "n", sp)
    assert argv[argv.index("--add-host") + 1] == "app.example.com:93.184.216.34"
    assert not any(SecretLike in " ".join(argv) for SecretLike in ("password", "SECRET"))


def test_zap_status_mapping_and_scope(tmp_path: Path) -> None:
    for code, raw, status in [(0, zap(), "passed"), (2, zap(alert()), "failed"), (1, zap(alert()), "failed"), (3, zap(alert()), "error"), (0, None, "error"), (0, b"junk", "error")]:  # fmt: skip
        ex, _, _ = make_executor(tmp_path, raw, code, resolver=PUBLIC, **ZAP_ON)
        res = ex.execute(request("zap_baseline", None, TARGET), lambda: False)
        assert res.status == status, (code, res)
    # an alert about a different host is dropped and the run is not a clean pass
    ex, _, _ = make_executor(tmp_path, zap(alert(instances=[{"uri": "https://evil.example.net/x"}])), 0, resolver=PUBLIC, **ZAP_ON)  # fmt: skip
    res = ex.execute(request("zap_active", None, TARGET), lambda: False)
    assert res.status == "error" and res.scan is None
    # infrastructure states are never findings
    s = make_settings(artifact_storage_dir=tmp_path, job_executor="docker", **ZAP_ON)
    runner = FakeRunner(lambda sp: SandboxResult(started=True, exit_code=137, timed_out=True))
    out = DockerSandboxExecutor(s, runner, PUBLIC).execute(request("zap_active", None, TARGET), lambda: False)  # type: ignore[arg-type]  # fmt: skip
    assert out.status == "timed_out" and out.scan is None


def test_existing_checks_still_get_no_network_and_the_base_image(tmp_path: Path) -> None:
    ex, runner, ref = make_executor(tmp_path, json.dumps({"errors": [], "results": []}).encode(), 0)
    ex.execute(request("bandit_static", ref), lambda: False)
    assert runner.specs[0].egress is None and runner.specs[0].image == "sentinel-sandbox-runner:stage8"  # fmt: skip


def test_zap_settings_are_validated() -> None:
    for bad in ({"sandbox_zap_network": "host"}, {"sandbox_zap_network": "bridge"}, {"sandbox_zap_network": "a b"}, {"sandbox_zap_image": "Bad Image!"}, {"sandbox_zap_tmp_mb": 4096}):  # fmt: skip
        with pytest.raises(ValueError):
            make_settings(**bad)
    assert make_settings().sandbox_zap_image is None and make_settings().sandbox_zap_egress_attested is False  # fmt: skip


# ---- de-duplication across scanners ----------------------------------------------------------


def cand(tool: str, path: str = "app/db.py", line: int = 7, cwe: int | None = 78, **over: Any) -> GroupCandidate:  # fmt: skip
    base = dict(id=uuid.uuid4(), detected_by=tool, category="static_analysis", source_id=uuid.UUID(int=1), file_path=path, line_number=line, cwe=cwe, component=None, aliases=[], fingerprint=f"{tool}:{uuid.uuid4().hex}", group_id=None)  # fmt: skip
    return GroupCandidate(**{**base, **over})


def test_two_tools_on_the_same_cwe_and_nearby_lines_are_grouped_not_merged() -> None:
    a, b, far, other_cwe, other_file, same_tool = cand("bandit", line=7), cand("semgrep", line=9), cand("semgrep", line=40), cand("semgrep", line=8, cwe=89), cand("semgrep", path="x.py", line=7), cand("bandit", line=8)  # fmt: skip
    groups = dedup.compute([a, b, far, other_cwe, other_file, same_tool])
    assert len(groups) == 1
    kind, key, members = groups[0]
    assert kind == "location" and key.startswith("location:") and set(members) == {a.id, b.id, same_tool.id}  # fmt: skip
    assert far.id not in members and other_cwe.id not in members and other_file.id not in members


def test_one_tool_alone_is_never_grouped_by_location() -> None:
    assert dedup.compute([cand("bandit", line=7), cand("bandit", line=8)]) == []


def test_line_chains_and_different_sources_are_respected() -> None:
    chain = [cand("bandit", line=10), cand("semgrep", line=13), cand("bandit", line=16)]
    ((_, _, members),) = dedup.compute(chain)
    assert len(members) == 3  # each within the window of its neighbour
    elsewhere = cand("semgrep", line=10, source_id=uuid.UUID(int=2))
    assert dedup.compute([cand("bandit", line=10), elsewhere]) == []


def test_advisories_for_the_same_component_that_share_an_alias_are_grouped() -> None:
    dependency = dict(category="dependency", file_path="poetry.lock", line_number=None, cwe=None)
    a = cand("dependency_audit", component="pypi:django@3.0.0", aliases=["PYSEC-1", "CVE-1"], **dependency)  # fmt: skip
    b = cand("dependency_audit", component="pypi:django@3.0.0", aliases=["GHSA-1", "CVE-1"], **dependency)  # fmt: skip
    c = cand("dependency_audit", component="pypi:django@3.0.0", aliases=["PYSEC-9"], **dependency)
    d = cand("dependency_audit", component="pypi:django@3.1.0", aliases=["CVE-1"], **dependency)
    ((kind, _, members),) = dedup.compute([a, b, c, d])
    assert kind == "advisory" and set(members) == {a.id, b.id}


def test_dynamic_findings_are_not_grouped_with_static_ones() -> None:
    dyn = cand("zap", category="dynamic", file_path="/login", line_number=None, component="GET https://a/login")  # fmt: skip
    assert dedup.compute([cand("semgrep", line=5), dyn]) == []


def test_group_keys_do_not_churn_when_members_come_and_go() -> None:
    a, b, c = cand("bandit", line=7), cand("semgrep", line=8), cand("semgrep", line=9)
    k1 = dedup.compute([a, b])[0][1]
    k2 = dedup.compute([a, b, c])[0][1]
    smallest = min([a, b, c], key=lambda x: x.fingerprint)
    assert (k1 == k2) == (smallest in (a, b))
