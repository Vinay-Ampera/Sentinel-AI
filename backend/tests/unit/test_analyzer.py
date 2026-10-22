import io
import json

from sentinel_ai.services.analyzer import analyze
from sentinel_ai.services.archive import ArchiveLimits, inspect_archive, open_archive
from support import SAMPLE_PROJECT, make_zip

LIMITS = ArchiveLimits(10**7, 10**7, 1000)


def run(files: dict[str, bytes | str], declared: str | None = None) -> dict:  # type: ignore[type-arg]
    with open_archive(io.BytesIO(make_zip(files))) as zf:
        return analyze(zf, inspect_archive(zf, LIMITS), declared)


def names(items: list[dict]) -> list[str]:  # type: ignore[type-arg]
    return [i["name"] for i in items]


def test_detects_languages_frameworks_tests_and_config_with_evidence() -> None:
    result = run(SAMPLE_PROJECT)
    facts = result["facts"]
    assert {"python", "javascript"} <= set(names(facts["languages"]))
    assert set(names(facts["frameworks"])) == {"react", "express", "vite", "fastapi", "openai"}
    react = next(f for f in facts["frameworks"] if f["name"] == "react")
    assert react["evidence"] == ["app/package.json: react"]  # facts carry their evidence
    assert set(names(facts["test_tools"])) == {"jest", "pytest"}
    assert facts["test_files"]["count"] == 2
    assert {"docker", "ci_github_actions", "env_example"} >= {"docker", "ci_github_actions"}
    assert "docker" in facts["config_files"] and "ci_github_actions" in facts["config_files"]
    assert facts["package_scripts"]["app/package.json#test"] == "jest"


def test_vendor_dirs_are_excluded_and_counted() -> None:
    facts = run(SAMPLE_PROJECT)["facts"]
    assert facts["archive"]["vendor_files_excluded"] == 1
    assert not any("node_modules" in str(x) for x in facts["test_files"]["examples"])


def test_facts_and_inferences_are_separate_and_inferences_have_basis() -> None:
    result = run(SAMPLE_PROJECT, declared="web_app")
    ids = {i["id"] for i in result["inferences"]}
    assert {
        "application_type:web_app",
        "application_type:rest_api",
        "application_type:ai_app",
    } <= ids
    for inference in result["inferences"]:
        assert inference["confidence"] in {"low", "medium", "high"} and inference["basis"]
    assert "inferences" not in result["facts"] and "application_type" not in json.dumps(
        result["facts"]
    )
    assert result["executed_code"] is False and result["method"] == "static_archive_inspection"


def test_gaps_report_unavailable_evidence_and_coverage_gaps() -> None:
    gaps = {g["id"]: g for g in run({"main.py": "print(1)"})["gaps"]}
    assert gaps["runtime_behavior"]["kind"] == "unavailable_evidence"
    assert {"dependency_vulnerabilities", "no_tests_detected", "no_ci_config"} <= set(gaps)
    full = {g["id"] for g in run(SAMPLE_PROJECT)["gaps"]}
    assert (
        "no_tests_detected" not in full and "no_coverage_tooling" in full and "no_lockfile" in full
    )


def test_declared_type_mismatch_is_flagged_as_low_confidence_inference() -> None:
    result = run({"requirements.txt": "fastapi\n"}, declared="web_app")
    mismatch = next(i for i in result["inferences"] if i["id"] == "declared_type_unsupported")
    assert mismatch["confidence"] == "low"


def test_sensitive_files_are_flagged_but_contents_never_stored() -> None:
    result = run(SAMPLE_PROJECT)
    assert result["facts"]["sensitive_files"]["env_file_present"] == [".env"]
    assert any(w["id"] == "sensitive_files_in_archive" for w in result["warnings"])
    assert "do-not-store-me" not in json.dumps(result)


def test_unparsable_and_oversized_manifests_are_reported_not_fatal() -> None:
    result = run({"package.json": "{not json", "sub/pyproject.toml": "= broken"})
    assert {w["id"] for w in result["warnings"]} == {"manifest_unparsable"}
    huge = run(
        {
            "package.json": '{"dependencies": {"react": "1"}}'
            + "".join(f" {i:07d}" for i in range(140_000))
        }
    )
    assert any(w["id"] == "manifest_truncated" for w in huge["warnings"])
    assert huge["facts"]["frameworks"] == []


def test_analysis_is_repeatable() -> None:
    first, second = (
        run(SAMPLE_PROJECT, "web_app"),
        run(dict(reversed(SAMPLE_PROJECT.items())), "web_app"),
    )
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_pyproject_poetry_and_pep621_dependencies() -> None:
    toml = (
        '[project]\ndependencies=["flask>=2"]\n[tool.poetry.group.dev.dependencies]\npytest="*"\n'
        "[tool.pytest.ini_options]\ntestpaths=['t']\n"
    )
    facts = run({"pyproject.toml": toml})["facts"]
    assert names(facts["frameworks"]) == ["flask"] and names(facts["test_tools"]) == ["pytest"]
