from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from repropilot.domain import CommandResult


def _patching_contracts():
    try:
        from repropilot.diagnosis import diagnose_failure
        from repropilot.domain import Diagnosis, PatchProposal, RiskLevel
        from repropilot.patching import (
            PatchApplyError,
            PatchTransaction,
            PatchValidationError,
            workspace_hash,
        )
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 5 patch transaction is not implemented: {exc}")
    return (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        PatchApplyError,
        PatchTransaction,
        PatchValidationError,
        diagnose_failure,
        workspace_hash,
    )


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-b", "main", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "config.txt").write_text("old\n", encoding="utf-8")
    subprocess.run(["git", "add", "config.txt"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=ReproPilot Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "fixture",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path


def _proposal(PatchProposal: Any, RiskLevel: Any, diff: str, paths: list[str]):
    return PatchProposal(
        diff=diff,
        explanation="Update the diagnosed configuration.",
        risk=RiskLevel.LOW,
        targeted_test=["pytest", "-q", "tests/test_config.py"],
        allowed_paths=paths,
    )


def _diagnosis(Diagnosis: Any, related_files: list[str]):
    return Diagnosis(
        category="configuration",
        root_cause="The configured value is stale.",
        evidence=["config error at line 1"],
        related_files=related_files,
        confidence=0.95,
    )


def _config_diff(old: str = "old", new: str = "new") -> str:
    return f"""diff --git a/config.txt b/config.txt
--- a/config.txt
+++ b/config.txt
@@ -1 +1 @@
-{old}
+{new}
"""


class FakeVerifier:
    def __init__(self, tmp_path: Path, exit_code: int) -> None:
        self.calls: list[list[str]] = []
        self.tmp_path = tmp_path
        self.exit_code = exit_code

    def run(self, argv: list[str]) -> CommandResult:
        self.calls.append(argv)
        logs = self.tmp_path / ".git" / "repropilot-test-logs"
        logs.mkdir(exist_ok=True)
        stdout = logs / "verify.stdout.log"
        stderr = logs / "verify.stderr.log"
        stdout.write_text("verification output", encoding="utf-8")
        stderr.write_text("", encoding="utf-8")
        return CommandResult(
            exit_code=self.exit_code,
            stdout_path=stdout,
            stderr_path=stderr,
            duration_seconds=0.1,
            argv=argv,
        )


def test_passing_targeted_test_keeps_the_applied_patch(repository: Path):
    (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        _,
        PatchTransaction,
        _,
        _,
        _,
    ) = _patching_contracts()
    verifier = FakeVerifier(repository, exit_code=0)
    transaction = PatchTransaction(
        repository,
        _proposal(PatchProposal, RiskLevel, _config_diff(), ["config.txt"]),
        _diagnosis(Diagnosis, ["config.txt"]),
        verifier,
    )

    transaction.validate()
    transaction.apply()
    result = transaction.verify()

    assert result.exit_code == 0
    assert (repository / "config.txt").read_text(encoding="utf-8") == "new\n"
    assert verifier.calls == [["pytest", "-q", "tests/test_config.py"]]


def test_failed_targeted_test_restores_exact_pre_patch_workspace(repository: Path):
    (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        _,
        PatchTransaction,
        _,
        _,
        workspace_hash,
    ) = _patching_contracts()
    before = workspace_hash(repository)
    before_bytes = (repository / "config.txt").read_bytes()
    transaction = PatchTransaction(
        repository,
        _proposal(PatchProposal, RiskLevel, _config_diff(), ["config.txt"]),
        _diagnosis(Diagnosis, ["config.txt"]),
        FakeVerifier(repository, exit_code=1),
    )

    transaction.apply()
    result = transaction.verify()

    assert result.exit_code == 1
    assert workspace_hash(repository) == before
    assert (repository / "config.txt").read_bytes() == before_bytes


def test_rejects_paths_outside_allowed_and_diagnosed_scope(repository: Path):
    (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        _,
        PatchTransaction,
        PatchValidationError,
        _,
        _,
    ) = _patching_contracts()
    transaction = PatchTransaction(
        repository,
        _proposal(PatchProposal, RiskLevel, _config_diff(), ["README.md"]),
        _diagnosis(Diagnosis, ["config.txt"]),
        FakeVerifier(repository, exit_code=0),
    )

    with pytest.raises(PatchValidationError, match="allowed_paths"):
        transaction.validate()
    assert (repository / "config.txt").read_text(encoding="utf-8") == "old\n"


def test_git_apply_check_rejects_an_invalid_hunk_before_mutation(repository: Path):
    (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        PatchApplyError,
        PatchTransaction,
        _,
        _,
        _,
    ) = _patching_contracts()
    before_bytes = (repository / "config.txt").read_bytes()
    transaction = PatchTransaction(
        repository,
        _proposal(PatchProposal, RiskLevel, _config_diff(old="missing"), ["config.txt"]),
        _diagnosis(Diagnosis, ["config.txt"]),
        FakeVerifier(repository, exit_code=0),
    )

    with pytest.raises(PatchApplyError, match="git apply --check"):
        transaction.apply()
    assert (repository / "config.txt").read_bytes() == before_bytes


@pytest.mark.parametrize(
    "unsafe_marker",
    [
        "GIT binary patch",
        "rename from config.txt",
        "deleted file mode 100644",
        "new file mode 120000",
    ],
)
def test_rejects_unsupported_patch_operations(repository: Path, unsafe_marker: str):
    (
        Diagnosis,
        PatchProposal,
        RiskLevel,
        _,
        PatchTransaction,
        PatchValidationError,
        _,
        _,
    ) = _patching_contracts()
    unsafe_diff = _config_diff() + unsafe_marker + "\n"
    transaction = PatchTransaction(
        repository,
        _proposal(PatchProposal, RiskLevel, unsafe_diff, ["config.txt"]),
        _diagnosis(Diagnosis, ["config.txt"]),
        FakeVerifier(repository, exit_code=0),
    )

    with pytest.raises(PatchValidationError):
        transaction.validate()


@pytest.mark.parametrize(
    ("log", "category"),
    [
        ("ModuleNotFoundError: No module named 'yaml'", "dependency"),
        ("FileNotFoundError: dataset/train does not exist", "path"),
        ("RuntimeError: CUDA is not available", "cuda_runtime"),
        ("ValueError: average must be macro or micro", "metric"),
        ("unexpected crash", "unknown"),
    ],
)
def test_diagnosis_classifies_failures_with_exact_log_evidence(log: str, category: str):
    *_, diagnose_failure, _ = _patching_contracts()

    diagnosis = diagnose_failure(
        ["python", "train.py"],
        f"setup line\n{log}\ntrailing line",
        ["train.py"],
    )

    assert diagnosis.category == category
    assert diagnosis.evidence == [log]
    assert diagnosis.related_files == ["train.py"]
