from __future__ import annotations

import stat
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

import repropilot.real_benchmark as real_benchmark
from repropilot.domain import ModelUsage, PatchProposal, RiskLevel
from repropilot.real_benchmark import (
    AcquisitionError,
    InjectionError,
    RealBenchmarkCase,
    acquire_repository,
    load_real_cases,
    prepare_injected_case,
    run_agent_case,
    run_probe,
)


def _commit_repository(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "benchmark@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Benchmark"], cwd=path, check=True)
    (path / "train.py").write_text("LEARNING_RATE = 0.1\n", encoding="utf-8")
    (path / "unused-weights.bin").write_bytes(b"not needed by benchmark")
    subprocess.run(["git", "add", "train.py", "unused-weights.bin"], cwd=path, check=True)
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


class FixedPatchGenerator:
    def __init__(self, proposal: PatchProposal) -> None:
        self.proposal = proposal
        self.usage: list[ModelUsage] = []

    def propose(self, *_args: object) -> PatchProposal:
        self.usage.append(
            ModelUsage(
                model="test-model",
                input_tokens=20,
                output_tokens=10,
                duration_seconds=0.1,
                estimated_cost_usd=None,
            )
        )
        return self.proposal


def _repair_proposal(*, replacement: str = "LEARNING_RATE = 0.1") -> PatchProposal:
    return PatchProposal(
        diff=(
            "diff --git a/train.py b/train.py\n"
            "--- a/train.py\n"
            "+++ b/train.py\n"
            "@@ -1 +1 @@\n"
            "-LEARNING_RATE = 0.001\n"
            f"+{replacement}\n"
        ),
        explanation="Restore the documented learning rate.",
        risk=RiskLevel.LOW,
        targeted_test=["python", "-m", "pytest", "-q"],
        allowed_paths=["train.py"],
    )


def _injected_workspace(tmp_path: Path) -> tuple[RealBenchmarkCase, Path]:
    workspace = tmp_path / "workspace"
    commit_sha = _commit_repository(workspace)
    injection = tmp_path / "fault.patch"
    injection.write_text(
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        "@@ -1 +1 @@\n"
        "-LEARNING_RATE = 0.1\n"
        "+LEARNING_RATE = 0.001\n",
        encoding="utf-8",
    )
    case = _case(str(workspace), commit_sha).model_copy(update={"injection": injection})
    return case, workspace


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
    assert result.tool_calls == 5
    assert (destination / "train.py").read_text(encoding="utf-8") == "LEARNING_RATE = 0.1\n"
    assert (destination / "unused-weights.bin").exists() is False


def test_acquisition_failure_is_separate_from_agent_failure(tmp_path: Path) -> None:
    missing = tmp_path / "missing-repository"
    case = _case(str(missing), "a" * 40)

    with pytest.raises(AcquisitionError) as captured:
        acquire_repository(case, tmp_path / "checkout", retries=2)

    assert captured.value.attempts == 2
    assert "repository acquisition failed" in str(captured.value).lower()


def test_acquisition_timeout_is_classified_and_retried(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def time_out(_argv: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        raise subprocess.TimeoutExpired(["git", "clone"], 120)

    monkeypatch.setattr(real_benchmark, "_git", time_out)
    case = _case(str(tmp_path / "source"), "a" * 40)

    with pytest.raises(AcquisitionError, match="timed out") as captured:
        acquire_repository(case, tmp_path / "checkout", retries=2)

    assert captured.value.attempts == 2
    assert calls == 2


def test_acquisition_refuses_to_overwrite_preexisting_destination(tmp_path: Path) -> None:
    destination = tmp_path / "checkout"
    destination.mkdir()
    protected = destination / "user-file.txt"
    protected.write_text("keep me", encoding="utf-8")

    with pytest.raises(FileExistsError, match="already exists"):
        acquire_repository(
            _case(str(tmp_path / "source"), "a" * 40), destination, retries=1
        )

    assert protected.read_text(encoding="utf-8") == "keep me"


def test_retry_removes_read_only_git_residue_created_by_failed_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0
    destination = tmp_path / "checkout"

    def fail_with_residue(argv: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        if calls == 1:
            destination.mkdir()
            residue = destination / "pack.idx"
            residue.write_bytes(b"partial")
            residue.chmod(stat.S_IREAD)
            raise subprocess.TimeoutExpired(["git", *argv], 120)
        return subprocess.CompletedProcess(["git", *argv], 1, "", "network failed")

    monkeypatch.setattr(real_benchmark, "_git", fail_with_residue)

    with pytest.raises(AcquisitionError, match="network failed"):
        acquire_repository(
            _case(str(tmp_path / "source"), "a" * 40), destination, retries=2
        )

    assert destination.exists() is False


def test_probe_checks_source_without_importing_or_executing_it(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    marker = tmp_path / "executed.txt"
    (workspace / "train.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "LEARNING_RATE = 0.1\n",
        encoding="utf-8",
    )
    case = _case(str(workspace), "b" * 40)

    result = run_probe(case, workspace)

    assert result.passed is True
    assert result.related_file == "train.py"
    assert marker.exists() is False


def test_prepare_injected_case_proves_baseline_passes_and_fault_fails(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    commit_sha = _commit_repository(workspace)
    injection = tmp_path / "fault.patch"
    injection.write_text(
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        "@@ -1 +1 @@\n"
        "-LEARNING_RATE = 0.1\n"
        "+LEARNING_RATE = 0.001\n",
        encoding="utf-8",
    )
    case = _case(str(workspace), commit_sha).model_copy(update={"injection": injection})

    result = prepare_injected_case(case, workspace)

    assert result.baseline_probe.passed is True
    assert result.injected_probe.passed is False
    assert result.injected_probe.output == "CONFIGURATION ERROR in train.py"
    assert result.tool_calls == 4
    assert "LEARNING_RATE = 0.001" in (workspace / "train.py").read_text(encoding="utf-8")


def test_prepare_injected_case_rejects_fault_that_does_not_break_probe(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    commit_sha = _commit_repository(workspace)
    injection = tmp_path / "no-op.patch"
    injection.write_text(
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        "@@ -1 +1,2 @@\n"
        " LEARNING_RATE = 0.1\n"
        "+COMMENT = 'unrelated'\n",
        encoding="utf-8",
    )
    case = _case(str(workspace), commit_sha).model_copy(update={"injection": injection})

    with pytest.raises(InjectionError, match="did not break"):
        prepare_injected_case(case, workspace)


def test_manifest_failure_messages_drive_expected_diagnosis_categories() -> None:
    from repropilot.diagnosis import diagnose_failure

    root = Path(__file__).parents[1]
    cases = load_real_cases(root / "benchmark" / "real-projects.yaml", root=root)

    observed = {
        diagnose_failure(["probe"], case.probe.failure_message, case.allowed_paths).category
        for case in cases
    }

    assert observed == {case.expected_category for case in cases}


def test_all_real_injection_patches_are_valid_unified_diffs() -> None:
    root = Path(__file__).parents[1]
    patches = sorted((root / "benchmark" / "real-injections").glob("*.patch"))

    results = [
        subprocess.run(
            ["git", "apply", "--numstat", str(patch)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        for patch in patches
    ]

    assert len(patches) == 6
    failures = [
        (patch.name, result.stderr)
        for patch, result in zip(patches, results, strict=True)
        if result.returncode
    ]
    assert failures == []


def test_agent_case_localizes_repairs_and_records_evidence(tmp_path: Path) -> None:
    case, workspace = _injected_workspace(tmp_path)
    generator = FixedPatchGenerator(_repair_proposal())

    result = run_agent_case(case, workspace, generator)

    assert result.status == "completed"
    assert result.localization_correct is True
    assert result.diagnosed_category == "configuration"
    assert result.diagnosed_files == ["train.py"]
    assert result.repair_succeeded is True
    assert result.post_fix_tests_passed is True
    assert result.unrelated_change_rate == 0
    assert result.patch_attempts == 1
    assert result.model_calls == 1
    assert result.input_tokens == 20
    assert result.output_tokens == 10
    assert result.model_cost_usd is None
    assert result.patch_diff == _repair_proposal().diff
    assert run_probe(case, workspace).passed is True


def test_agent_case_stops_at_correct_high_risk_approval_gate(tmp_path: Path) -> None:
    case, workspace = _injected_workspace(tmp_path)
    case = case.model_copy(
        update={"expected_category": "metric", "expected_outcome": "approval"}
    )
    case.probe.failure_message = "METRIC ERROR in train.py: wrong averaging behavior"
    generator = FixedPatchGenerator(_repair_proposal())

    result = run_agent_case(case, workspace, generator, approve_high_risk=False)

    assert result.status == "approval_required"
    assert result.approval_required is True
    assert result.approval_gate_correct is True
    assert result.repair_succeeded is False
    assert "LEARNING_RATE = 0.001" in (workspace / "train.py").read_text(encoding="utf-8")


def test_agent_case_rolls_back_failed_patch_before_next_attempt(tmp_path: Path) -> None:
    case, workspace = _injected_workspace(tmp_path)
    generator = FixedPatchGenerator(_repair_proposal(replacement="LEARNING_RATE = 0.2"))

    result = run_agent_case(case, workspace, generator, max_attempts=1)

    assert result.status == "completed"
    assert result.repair_succeeded is False
    assert result.post_fix_tests_passed is False
    assert result.patch_attempts == 1
    assert "LEARNING_RATE = 0.001" in (workspace / "train.py").read_text(encoding="utf-8")
