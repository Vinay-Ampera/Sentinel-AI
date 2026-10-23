"""Stage 10: the offline dependency audit in a REAL locked-down container.

Builds a throw-away image from the repository's sandbox files plus a SYNTHETIC advisory bundle
(fake ids; never real advisory data), runs the real executor against it, and removes the image.
Needs Docker, the local ``python:3.12-slim`` base and ``sandbox/vendor`` (``make sandbox-image``).
It proves OUR pipeline (lockfile parsing, range matching, framing, host parsing, the image-label
age check, the container recipe), not that any real advisory is matched. Semgrep and ZAP have no
equivalent here: their images could not be built or run (ADR-0008).
"""

import datetime
import importlib.util
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from sentinel_ai.execution.docker_executor import DockerSandboxExecutor
from sentinel_ai.execution.docker_runner import DockerRunner
from sentinel_ai.execution.interface import ExecutionRequest, WorkspaceRef
from sentinel_ai.services.artifact_store import ArtifactStore, sha256_bytes
from support import make_settings, make_zip

SANDBOX = Path(__file__).resolve().parents[3] / "sandbox"
_probe = DockerRunner("probe")
pytestmark = pytest.mark.skipif(
    not (_probe.available() and _probe.image_exists("python:3.12-slim") and (SANDBOX / "vendor").is_dir()),
    reason="Docker, the python:3.12-slim base or sandbox/vendor (make sandbox-image) is missing",
)  # fmt: skip


def _advisory(adv_id: str, name: str, eco: str, fixed: str, aliases: list[str]) -> dict:
    return {
        "id": adv_id, "aliases": aliases, "summary": "SYNTHETIC test advisory",
        "database_specific": {"severity": "HIGH", "cwe_ids": ["CWE-79"]},
        "affected": [{"package": {"ecosystem": eco, "name": name}, "ranges": [{"type": "ECOSYSTEM", "events": [{"introduced": "0"}, {"fixed": fixed}]}]}],
    }  # fmt: skip


@pytest.fixture(scope="module")
def image(tmp_path_factory: pytest.TempPathFactory):  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("advisories", SANDBOX / "advisories.py")
    assert spec and spec.loader
    adv = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adv)
    ctx = tmp_path_factory.mktemp("sbx")
    for name in ("Dockerfile", ".dockerignore", "entry.py", "smoke.py", "dep_audit.py"):
        shutil.copy(SANDBOX / name, ctx / name)
    shutil.copytree(SANDBOX / "vendor", ctx / "vendor")
    (ctx / "advisories").mkdir()
    fetched = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    feeds = {
        "PyPI": ("pypi.json", [_advisory("SYN-PY-1", "django", "PyPI", "3.0.1", ["CVE-0000-0001"])]),
        "npm": ("npm.json", [_advisory("SYN-NPM-1", "lodash", "npm", "4.17.21", [])]),
    }  # fmt: skip
    for eco, (filename, records) in feeds.items():
        packages: dict[str, list] = {}
        for r in records:
            for k, v in adv.compact(r, eco).items():
                packages.setdefault(k, []).extend(v)
        doc = {"schema": 1, "ecosystem": eco, "source": "synthetic", "fetched_at": fetched, "advisory_count": len(records), "packages": packages}  # fmt: skip
        (ctx / "advisories" / filename).write_text(json.dumps(doc))
    tag = f"sentinel-sandbox-runner:s10-test-{uuid.uuid4().hex[:8]}"
    build = subprocess.run(  # noqa: S603
        ["docker", "build", "-q", "-t", tag, "--build-arg", f"ADVISORY_FETCHED_AT={fetched}", str(ctx)],  # noqa: S607
        capture_output=True, timeout=300, check=False,
    )  # fmt: skip
    if build.returncode != 0:
        pytest.skip("could not build the throw-away image (offline base pull?)")
    yield tag
    subprocess.run(["docker", "rmi", "-f", tag], capture_output=True, timeout=60, check=False)  # noqa: S603, S607


def test_dependency_audit_runs_offline_in_a_real_container(image: str, tmp_path: Path) -> None:
    files = {
        "poetry.lock": '[[package]]\nname = "Django"\nversion = "3.0.0"\n\n[[package]]\nname = "safe"\nversion = "1.0"\n',
        "requirements.txt": "django==3.0.1\n",  # already fixed: must not match
        "web/package-lock.json": json.dumps({"lockfileVersion": 3, "packages": {"": {}, "node_modules/lodash": {"version": "4.17.20"}}}),
    }  # fmt: skip
    data = make_zip(files)
    key = f"projects/{uuid.uuid4()}/uploads/a.zip"
    store = ArtifactStore(tmp_path)
    store.path_for(key).parent.mkdir(parents=True)
    store.path_for(key).write_bytes(data)
    scope = "s10-deps-" + uuid.uuid4().hex[:8]
    settings = make_settings(artifact_storage_dir=tmp_path, job_executor="docker", sandbox_image=image, sandbox_scope=scope)  # fmt: skip
    executor = DockerSandboxExecutor(settings)
    request = ExecutionRequest(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "dependency_audit", 1, 120, uuid.uuid4(), WorkspaceRef(key, sha256_bytes(data), len(data)), {})  # fmt: skip
    try:
        out = executor.execute(request, lambda: False)
    finally:
        assert executor.terminate(request.batch_id)
    assert out.status == "failed", out.summary
    assert out.scan and out.scan.complete and out.scan.tool == "dependency_audit"
    assert sorted((f.rule_id, f.component) for f in out.scan.findings) == [
        ("SYN-NPM-1", "npm:lodash@4.17.20"),
        ("SYN-PY-1", "pypi:Django@3.0.0"),
    ]
    manifest = json.loads(next(e for e in out.evidence if e.name == "manifest.json").data)
    assert manifest["network"] == "none" and manifest["advisory_data_fetched_at"]
    host = manifest["container"]
    assert host["NetworkMode"] == "none" and host["ReadonlyRootfs"] is True and host["CapDrop"] == ["ALL"]  # fmt: skip
    assert not host["Privileged"] and not host["Binds"]
