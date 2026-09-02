from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from repropilot.diagnosis import diagnose_failure
from repropilot.domain import DiagnosisCategory
from repropilot.policy import assess_patch


class BenchmarkCase(BaseModel):
    id: str = Field(min_length=1)
    fixture: Path
    injection: Path
    expected_category: DiagnosisCategory
    expected_root_cause: str = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)
    expected_outcome: Literal["auto_fix", "approval"]


class CaseObservation(BaseModel):
    diagnosed_category: DiagnosisCategory
    changed_lines: dict[str, set[int]] = Field(default_factory=dict)
    repair_succeeded: bool = False
    post_fix_tests_passed: bool = False
    patch_attempts: int = Field(default=0, ge=0)
    model_calls: int = Field(default=0, ge=0)
    tool_calls: int = Field(default=0, ge=0)
    wall_time_seconds: float = Field(default=0, ge=0)
    model_cost_usd: float = Field(default=0, ge=0)
    approval_required: bool = False
    safety_invariants_passed: bool = True


class BenchmarkResult(BaseModel):
    case_id: str
    localization_correct: bool
    repair_succeeded: bool
    post_fix_tests_passed: bool
    unrelated_change_rate: float = Field(ge=0, le=1)
    unrelated_changed_lines: int = Field(ge=0)
    total_changed_lines: int = Field(ge=0)
    patch_attempts: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    wall_time_seconds: float = Field(ge=0)
    model_cost_usd: float = Field(ge=0)
    approval_gate_correct: bool
    safety_invariants_passed: bool


class BenchmarkSummary(BaseModel):
    mode: str
    case_count: int = Field(ge=0)
    error_localization_rate: float = Field(ge=0, le=1)
    repair_success_rate: float = Field(ge=0, le=1)
    post_fix_test_pass_rate: float = Field(ge=0, le=1)
    unrelated_change_rate: float = Field(ge=0, le=1)
    mean_patch_attempts: float = Field(ge=0)
    total_model_calls: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)
    total_wall_time_seconds: float = Field(ge=0)
    total_model_cost_usd: float = Field(ge=0)
    safety_invariants_passed: bool


def load_cases(path: Path, *, root: Path | None = None) -> list[BenchmarkCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError("benchmark cases file must contain a cases list")
    base = root or path.parent.parent
    cases = [BenchmarkCase.model_validate(item) for item in raw["cases"]]
    return [
        case.model_copy(
            update={
                "fixture": (base / case.fixture).resolve(),
                "injection": (base / case.injection).resolve(),
            }
        )
        for case in cases
    ]


def evaluate_case(case: BenchmarkCase, observation: CaseObservation) -> BenchmarkResult:
    total_lines = sum(len(lines) for lines in observation.changed_lines.values())
    unrelated_lines = sum(
        len(lines)
        for path, lines in observation.changed_lines.items()
        if path not in case.allowed_paths
    )
    expected_approval = case.expected_outcome == "approval"
    return BenchmarkResult(
        case_id=case.id,
        localization_correct=observation.diagnosed_category == case.expected_category,
        repair_succeeded=observation.repair_succeeded,
        post_fix_tests_passed=observation.post_fix_tests_passed,
        unrelated_change_rate=unrelated_lines / total_lines if total_lines else 0,
        unrelated_changed_lines=unrelated_lines,
        total_changed_lines=total_lines,
        patch_attempts=observation.patch_attempts,
        model_calls=observation.model_calls,
        tool_calls=observation.tool_calls,
        wall_time_seconds=observation.wall_time_seconds,
        model_cost_usd=observation.model_cost_usd,
        approval_gate_correct=observation.approval_required == expected_approval,
        safety_invariants_passed=observation.safety_invariants_passed,
    )


def aggregate_results(results: list[BenchmarkResult], *, mode: str) -> BenchmarkSummary:
    count = len(results)
    total_lines = sum(result.total_changed_lines for result in results)
    unrelated_lines = sum(result.unrelated_changed_lines for result in results)
    denominator = count or 1
    return BenchmarkSummary(
        mode=mode,
        case_count=count,
        error_localization_rate=sum(r.localization_correct for r in results) / denominator,
        repair_success_rate=sum(r.repair_succeeded for r in results) / denominator,
        post_fix_test_pass_rate=sum(r.post_fix_tests_passed for r in results) / denominator,
        unrelated_change_rate=unrelated_lines / total_lines if total_lines else 0,
        mean_patch_attempts=sum(r.patch_attempts for r in results) / denominator,
        total_model_calls=sum(r.model_calls for r in results),
        total_tool_calls=sum(r.tool_calls for r in results),
        total_wall_time_seconds=sum(r.wall_time_seconds for r in results),
        total_model_cost_usd=sum(r.model_cost_usd for r in results),
        safety_invariants_passed=all(
            r.safety_invariants_passed and r.approval_gate_correct for r in results
        ),
    )


def run_reference_case(case: BenchmarkCase) -> BenchmarkResult:
    """Run a deterministic harness-validation baseline using the inverse injected patch."""
    started = time.monotonic()
    fixture_hash = _tree_hash(case.fixture)
    tool_calls = 0
    with tempfile.TemporaryDirectory(prefix=f"repropilot-{case.id}-") as temporary:
        workspace = Path(temporary) / "repository"
        shutil.copytree(case.fixture, workspace)

        baseline = _run_tests(workspace)
        tool_calls += 1
        if baseline.returncode != 0:
            raise RuntimeError(f"baseline failed for {case.id}: {baseline.stderr}")

        injected = _git_apply(workspace, case.injection)
        tool_calls += 1
        if injected.returncode != 0:
            raise RuntimeError(f"injection failed for {case.id}: {injected.stderr}")

        failed = _run_tests(workspace)
        tool_calls += 1
        if failed.returncode == 0:
            raise RuntimeError(f"injection did not fail tests for {case.id}")

        diagnosis = diagnose_failure(
            [sys.executable, "-m", "pytest", "-q"],
            f"{failed.stdout}\n{failed.stderr}",
            case.allowed_paths,
        )
        tool_calls += 1
        repair_diff = _reverse_diff(case.injection.read_text(encoding="utf-8"))
        risk = assess_patch(repair_diff, diagnosis)
        tool_calls += 1

        repaired = _git_apply(workspace, case.injection, reverse=True)
        tool_calls += 1
        post_fix = _run_tests(workspace)
        tool_calls += 1

    safety_ok = fixture_hash == _tree_hash(case.fixture)
    observation = CaseObservation(
        diagnosed_category=diagnosis.category,
        changed_lines=changed_lines_from_diff(repair_diff),
        repair_succeeded=repaired.returncode == 0,
        post_fix_tests_passed=post_fix.returncode == 0,
        patch_attempts=1,
        model_calls=0,
        tool_calls=tool_calls,
        wall_time_seconds=time.monotonic() - started,
        model_cost_usd=0,
        approval_required=risk.requires_approval,
        safety_invariants_passed=safety_ok,
    )
    return evaluate_case(case, observation)


def changed_lines_from_diff(diff: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_path: str | None = None
    line_number = 0
    for line in diff.splitlines():
        if line.startswith("diff --git a/"):
            current_path = line.split(" b/", 1)[1]
            changed.setdefault(current_path, set())
        elif line.startswith("@@"):
            new_range = line.split("+")[1].split(" ", 1)[0]
            line_number = int(new_range.split(",", 1)[0])
        elif current_path is not None and line.startswith("+") and not line.startswith("+++"):
            changed[current_path].add(line_number)
            line_number += 1
        elif current_path is not None and line.startswith("-") and not line.startswith("---"):
            changed[current_path].add(max(line_number, 1))
        elif current_path is not None and not line.startswith("\\"):
            line_number += 1
    return changed


def _run_tests(workspace: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _git_apply(
    workspace: Path, patch: Path, *, reverse: bool = False
) -> subprocess.CompletedProcess[str]:
    argv = ["git", "apply", "--whitespace=nowarn"]
    if reverse:
        argv.append("--reverse")
    argv.append(str(patch))
    return subprocess.run(
        argv,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def _reverse_diff(diff: str) -> str:
    reversed_lines: list[str] = []
    for line in diff.splitlines(keepends=True):
        if line.startswith("+++"):
            reversed_lines.append("---" + line[3:])
        elif line.startswith("---"):
            reversed_lines.append("+++" + line[3:])
        elif line.startswith("+"):
            reversed_lines.append("-" + line[1:])
        elif line.startswith("-"):
            reversed_lines.append("+" + line[1:])
        else:
            reversed_lines.append(line)
    return "".join(reversed_lines)


def _tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()
