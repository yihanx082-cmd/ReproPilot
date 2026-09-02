from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from repropilot.real_benchmark import (
    AcquisitionError,
    RealBenchmarkCase,
    acquire_repository,
    load_real_cases,
)


def _commit_repository(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "benchmark@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Benchmark"], cwd=path, check=True)
    (path / "train.py").write_text("LEARNING_RATE = 0.1\n", encoding="utf-8")
    subprocess.run(["git", "add", "train.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _case(repository: str, commit_sha: str) -> RealBenchmarkCase:
    return RealBenchmarkCase(
        id="learning-rate",
        repository_url=repository,
        commit_sha=commit_sha,
        license="MIT",
        injection=Path("benchmark/real-injections/lr.patch"),
        expected_category="configuration",
        expected_root_cause="documented learning rate differs",
        allowed_paths=["train.py"],
        expected_outcome="auto_fix",
        probe={
            "path": "train.py",
            "required_text": "LEARNING_RATE = 0.1",
            "failure_message": "CONFIGURATION ERROR in train.py",
        },
    )


def test_real_case_rejects_floating_commit_reference() -> None:
    with pytest.raises(ValidationError, match="commit_sha"):
        _case("https://github.com/example/project.git", "main")


def test_real_manifest_pins_three_repositories_and_six_faults() -> None:
    root = Path(__file__).parents[1]
    cases = load_real_cases(root / "benchmark" / "real-projects.yaml", root=root)

    assert len(cases) == 6
    assert len({case.id for case in cases}) == 6
    assert len({case.repository_url for case in cases}) == 3
    assert all(len(case.commit_sha) == 40 for case in cases)
    assert all(case.injection.is_file() for case in cases)
    assert {case.expected_category.value for case in cases} == {
        "dependency",
        "path",
        "configuration",
        "cuda_runtime",
        "metric",
        "data",
    }


def test_acquisition_checks_out_exact_pinned_commit(tmp_path: Path) -> None:
    source = tmp_path / "source"
    commit_sha = _commit_repository(source)
    destination = tmp_path / "checkout"

    result = acquire_repository(_case(str(source), commit_sha), destination)

    assert result.workspace == destination.resolve()
    assert result.commit_sha == commit_sha
    assert result.attempts == 1
    assert result.tool_calls == 3
    assert (destination / "train.py").read_text(encoding="utf-8") == "LEARNING_RATE = 0.1\n"


def test_acquisition_failure_is_separate_from_agent_failure(tmp_path: Path) -> None:
    missing = tmp_path / "missing-repository"
    case = _case(str(missing), "a" * 40)

    with pytest.raises(AcquisitionError) as captured:
        acquire_repository(case, tmp_path / "checkout", retries=2)

    assert captured.value.attempts == 2
    assert "repository acquisition failed" in str(captured.value).lower()
