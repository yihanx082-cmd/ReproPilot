from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from repropilot.domain import DiagnosisCategory


class ProbeSpec(BaseModel):
    path: str = Field(min_length=1)
    required_text: str | None = None
    forbidden_text: str | None = None
    expected_occurrences: int = Field(default=1, ge=1)
    failure_message: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_an_invariant(self) -> ProbeSpec:
        if self.required_text is None and self.forbidden_text is None:
            raise ValueError("probe requires required_text or forbidden_text")
        return self


class RealBenchmarkCase(BaseModel):
    id: str = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str = Field(min_length=1)
    injection: Path
    expected_category: DiagnosisCategory
    expected_root_cause: str = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)
    expected_outcome: Literal["auto_fix", "approval"]
    probe: ProbeSpec


class AcquisitionResult(BaseModel):
    workspace: Path
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    attempts: int = Field(ge=1)
    tool_calls: int = Field(ge=1)


class AcquisitionError(RuntimeError):
    def __init__(self, message: str, *, attempts: int) -> None:
        super().__init__(message)
        self.attempts = attempts


class InjectionError(RuntimeError):
    """Raised when a benchmark fault is invalid for its pinned source."""


class ProbeResult(BaseModel):
    passed: bool
    related_file: str = Field(min_length=1)
    output: str = Field(min_length=1)


class InjectionResult(BaseModel):
    baseline_probe: ProbeResult
    injected_probe: ProbeResult
    tool_calls: int = Field(ge=0)


def load_real_cases(path: Path, *, root: Path | None = None) -> list[RealBenchmarkCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list):
        raise ValueError("real benchmark cases file must contain a cases list")
    base = root or path.parent.parent
    cases = [RealBenchmarkCase.model_validate(item) for item in raw["cases"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("real benchmark case IDs must be unique")
    return [
        case.model_copy(update={"injection": (base / case.injection).resolve()})
        for case in cases
    ]


def acquire_repository(
    case: RealBenchmarkCase,
    destination: Path,
    *,
    retries: int = 3,
) -> AcquisitionResult:
    if retries < 1:
        raise ValueError("retries must be at least 1")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"Acquisition destination already exists: {destination}")
    last_error = "unknown Git error"
    tool_calls = 0
    for attempt in range(1, retries + 1):
        if destination.exists():
            _remove_acquisition_workspace(destination)
        try:
            clone = _git(
                [
                    "clone",
                    "--filter=blob:none",
                    "--no-checkout",
                    case.repository_url,
                    str(destination),
                ]
            )
            tool_calls += 1
            if clone.returncode != 0:
                last_error = clone.stderr.strip()
                continue
            sparse_init = _git(
                ["-C", str(destination), "sparse-checkout", "init", "--no-cone"]
            )
            tool_calls += 1
            if sparse_init.returncode != 0:
                last_error = sparse_init.stderr.strip()
                continue
            sparse_set = _git(
                [
                    "-C",
                    str(destination),
                    "sparse-checkout",
                    "set",
                    "--no-cone",
                    "--skip-checks",
                    *case.allowed_paths,
                ]
            )
            tool_calls += 1
            if sparse_set.returncode != 0:
                last_error = sparse_set.stderr.strip()
                continue
            checkout = _git(
                ["-C", str(destination), "checkout", "--detach", case.commit_sha]
            )
            tool_calls += 1
            if checkout.returncode != 0:
                last_error = checkout.stderr.strip()
                continue
            resolved = _git(["-C", str(destination), "rev-parse", "HEAD"])
            tool_calls += 1
        except subprocess.TimeoutExpired as exc:
            tool_calls += 1
            last_error = f"Git command timed out after {exc.timeout} seconds"
            continue
        actual_sha = resolved.stdout.strip()
        if resolved.returncode == 0 and actual_sha == case.commit_sha:
            return AcquisitionResult(
                workspace=destination,
                commit_sha=actual_sha,
                attempts=attempt,
                tool_calls=tool_calls,
            )
        last_error = resolved.stderr.strip() or f"expected {case.commit_sha}, got {actual_sha}"

    if destination.exists():
        _remove_acquisition_workspace(destination)
    raise AcquisitionError(
        f"Repository acquisition failed after {retries} attempts: {last_error}",
        attempts=retries,
    )


def run_probe(case: RealBenchmarkCase, workspace: Path) -> ProbeResult:
    root = workspace.resolve()
    candidate = (root / case.probe.path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise InjectionError(f"Probe path is missing or escapes workspace: {case.probe.path}")
    content = candidate.read_text(encoding="utf-8", errors="replace")
    passed = True
    if case.probe.required_text is not None:
        passed = content.count(case.probe.required_text) == case.probe.expected_occurrences
    if case.probe.forbidden_text is not None and case.probe.forbidden_text in content:
        passed = False
    return ProbeResult(
        passed=passed,
        related_file=case.probe.path,
        output="probe passed" if passed else case.probe.failure_message,
    )


def prepare_injected_case(case: RealBenchmarkCase, workspace: Path) -> InjectionResult:
    baseline = run_probe(case, workspace)
    if not baseline.passed:
        raise InjectionError(f"Pinned baseline failed its probe: {baseline.output}")

    checked = _git_apply(workspace, case.injection, check_only=True)
    if checked.returncode != 0:
        raise InjectionError(f"Injection patch does not apply: {checked.stderr.strip()}")
    applied = _git_apply(workspace, case.injection)
    if applied.returncode != 0:
        raise InjectionError(f"Injection patch failed: {applied.stderr.strip()}")

    injected = run_probe(case, workspace)
    if injected.passed:
        _git_apply(workspace, case.injection, reverse=True)
        raise InjectionError(f"Injection did not break probe for {case.id}")
    return InjectionResult(
        baseline_probe=baseline,
        injected_probe=injected,
        tool_calls=4,
    )


def _git(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _git_apply(
    workspace: Path,
    patch: Path,
    *,
    check_only: bool = False,
    reverse: bool = False,
) -> subprocess.CompletedProcess[str]:
    argv = ["git", "apply", "--whitespace=nowarn"]
    if check_only:
        argv.append("--check")
    if reverse:
        argv.append("--reverse")
    argv.append(str(patch))
    return subprocess.run(
        argv,
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _remove_acquisition_workspace(path: Path) -> None:
    def clear_read_only(
        function: Callable[[str], object], target: str, _error: BaseException
    ) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onexc=clear_read_only)
