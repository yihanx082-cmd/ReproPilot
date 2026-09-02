from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from collections.abc import Callable
from html import escape
from pathlib import Path
from types import TracebackType
from typing import Literal, Protocol

import yaml
from openai import OpenAIError
from pydantic import BaseModel, Field, model_validator

from repropilot.benchmark import changed_lines_from_diff
from repropilot.diagnosis import diagnose_failure
from repropilot.domain import (
    CommandResult,
    Diagnosis,
    DiagnosisCategory,
    ModelUsage,
    PatchProposal,
)
from repropilot.patching import PatchApplyError, PatchTransaction
from repropilot.policy import assess_patch


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


class RealCaseResult(BaseModel):
    case_id: str
    repository_url: str
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    status: Literal[
        "completed",
        "approval_required",
        "acquisition_failed",
        "injection_failed",
        "model_failed",
    ]
    localization_correct: bool
    diagnosed_category: DiagnosisCategory
    diagnosed_files: list[str] = Field(default_factory=list)
    repair_succeeded: bool
    post_fix_tests_passed: bool
    unrelated_change_rate: float = Field(ge=0, le=1)
    unrelated_changed_lines: int = Field(ge=0)
    total_changed_lines: int = Field(ge=0)
    patch_attempts: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    wall_time_seconds: float = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    model_cost_usd: float | None = Field(default=None, ge=0)
    approval_required: bool
    approval_gate_correct: bool
    safety_invariants_passed: bool
    patch_diff: str | None = None
    failure_reason: str | None = None


class RealBenchmarkSummary(BaseModel):
    mode: str
    case_count: int = Field(ge=0)
    evaluated_case_count: int = Field(ge=0)
    infrastructure_failure_count: int = Field(ge=0)
    pending_approval_count: int = Field(ge=0)
    acquisition_success_rate: float = Field(ge=0, le=1)
    benchmark_completion_rate: float = Field(ge=0, le=1)
    error_localization_rate: float = Field(ge=0, le=1)
    repair_success_rate: float = Field(ge=0, le=1)
    post_fix_test_pass_rate: float = Field(ge=0, le=1)
    unrelated_change_rate: float = Field(ge=0, le=1)
    mean_patch_attempts: float = Field(ge=0)
    total_model_calls: int = Field(ge=0)
    total_tool_calls: int = Field(ge=0)
    total_wall_time_seconds: float = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_model_cost_usd: float | None = Field(default=None, ge=0)
    safety_invariants_passed: bool


class MeasuredPatchGenerator(Protocol):
    usage: list[ModelUsage]

    def propose(
        self, diagnosis: Diagnosis, worktree: Path, log_tail: str
    ) -> PatchProposal: ...


class _UnusedVerifier:
    def run(self, argv: list[str]) -> CommandResult:
        del argv
        raise RuntimeError("Real benchmark verifies patches with a semantic probe")


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


def run_agent_case(
    case: RealBenchmarkCase,
    workspace: Path,
    patch_generator: MeasuredPatchGenerator,
    *,
    max_attempts: int = 3,
    approve_high_risk: bool = False,
) -> RealCaseResult:
    if max_attempts < 1 or max_attempts > 3:
        raise ValueError("max_attempts must be between 1 and 3")
    started = time.monotonic()
    prepared = prepare_injected_case(case, workspace)
    tool_calls = prepared.tool_calls
    diagnosis = diagnose_failure(
        ["semantic-probe"],
        prepared.injected_probe.output,
        case.allowed_paths,
    )
    tool_calls += 1
    localization_correct = (
        diagnosis.category == case.expected_category
        and bool(set(diagnosis.related_files) & set(case.allowed_paths))
    )
    usage_start = len(patch_generator.usage)
    attempts = 0
    approval_required = False
    approval_gate_correct = False
    last_diff: str | None = None
    last_failure: str | None = None

    def result(
        *,
        status: Literal["completed", "approval_required", "model_failed"],
        repaired: bool,
        verified: bool,
        changed_lines: dict[str, set[int]] | None = None,
    ) -> RealCaseResult:
        observed_usage = patch_generator.usage[usage_start:]
        changes = changed_lines or {}
        total_lines = sum(len(lines) for lines in changes.values())
        unrelated_lines = sum(
            len(lines)
            for path, lines in changes.items()
            if path not in case.allowed_paths
        )
        known_costs = [
            usage.estimated_cost_usd
            for usage in observed_usage
            if usage.estimated_cost_usd is not None
        ]
        return RealCaseResult(
            case_id=case.id,
            repository_url=case.repository_url,
            commit_sha=case.commit_sha,
            status=status,
            localization_correct=localization_correct,
            diagnosed_category=diagnosis.category,
            diagnosed_files=diagnosis.related_files,
            repair_succeeded=repaired,
            post_fix_tests_passed=verified,
            unrelated_change_rate=unrelated_lines / total_lines if total_lines else 0,
            unrelated_changed_lines=unrelated_lines,
            total_changed_lines=total_lines,
            patch_attempts=attempts,
            model_calls=len(observed_usage),
            tool_calls=tool_calls,
            wall_time_seconds=time.monotonic() - started,
            input_tokens=sum(usage.input_tokens for usage in observed_usage),
            output_tokens=sum(usage.output_tokens for usage in observed_usage),
            model_cost_usd=sum(known_costs) if known_costs else None,
            approval_required=approval_required,
            approval_gate_correct=approval_gate_correct,
            safety_invariants_passed=unrelated_lines == 0,
            patch_diff=last_diff,
            failure_reason=last_failure,
        )

    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            proposal = patch_generator.propose(
                diagnosis,
                workspace,
                prepared.injected_probe.output,
            )
            tool_calls += 1
            decision = assess_patch(proposal.diff, diagnosis)
            tool_calls += 1
            proposal = proposal.model_copy(update={"risk": decision.level})
            last_diff = proposal.diff
            approval_required = decision.requires_approval
            approval_gate_correct = (
                approval_required == (case.expected_outcome == "approval")
            )
            changes = changed_lines_from_diff(proposal.diff)
            if approval_required and not approve_high_risk:
                return result(
                    status="approval_required",
                    repaired=False,
                    verified=False,
                    changed_lines=changes,
                )

            transaction = PatchTransaction(
                workspace,
                proposal,
                diagnosis,
                _UnusedVerifier(),
            )
            transaction.apply()
            tool_calls += 1
            post_fix = run_probe(case, workspace)
            tool_calls += 1
            if post_fix.passed:
                return result(
                    status="completed",
                    repaired=True,
                    verified=True,
                    changed_lines=changes,
                )
            transaction.rollback()
            tool_calls += 1
            last_failure = post_fix.output
        except (OpenAIError, PatchApplyError, RuntimeError, ValueError) as exc:
            last_failure = str(exc)

    return result(
        status="model_failed" if last_diff is None else "completed",
        repaired=False,
        verified=False,
        changed_lines=changed_lines_from_diff(last_diff) if last_diff else {},
    )


def infrastructure_failure_result(
    case: RealBenchmarkCase,
    *,
    status: Literal["acquisition_failed", "injection_failed"],
    reason: str,
    wall_time_seconds: float,
) -> RealCaseResult:
    return RealCaseResult(
        case_id=case.id,
        repository_url=case.repository_url,
        commit_sha=case.commit_sha,
        status=status,
        localization_correct=False,
        diagnosed_category=DiagnosisCategory.UNKNOWN,
        diagnosed_files=[],
        repair_succeeded=False,
        post_fix_tests_passed=False,
        unrelated_change_rate=0,
        unrelated_changed_lines=0,
        total_changed_lines=0,
        patch_attempts=0,
        model_calls=0,
        tool_calls=0,
        wall_time_seconds=wall_time_seconds,
        input_tokens=0,
        output_tokens=0,
        model_cost_usd=None,
        approval_required=False,
        approval_gate_correct=False,
        safety_invariants_passed=True,
        failure_reason=reason,
    )


def aggregate_real_results(
    results: list[RealCaseResult], *, mode: str
) -> RealBenchmarkSummary:
    case_count = len(results)
    infrastructure = [
        result
        for result in results
        if result.status in {"acquisition_failed", "injection_failed"}
    ]
    evaluated = [
        result for result in results if result.status in {"completed", "model_failed"}
    ]
    pending = [result for result in results if result.status == "approval_required"]
    case_denominator = case_count or 1
    evaluated_denominator = len(evaluated) or 1
    total_lines = sum(result.total_changed_lines for result in evaluated)
    unrelated_lines = sum(result.unrelated_changed_lines for result in evaluated)
    known_costs = [
        result.model_cost_usd
        for result in results
        if result.model_cost_usd is not None
    ]
    return RealBenchmarkSummary(
        mode=mode,
        case_count=case_count,
        evaluated_case_count=len(evaluated),
        infrastructure_failure_count=len(infrastructure),
        pending_approval_count=len(pending),
        acquisition_success_rate=(
            case_count
            - sum(result.status == "acquisition_failed" for result in results)
        )
        / case_denominator,
        benchmark_completion_rate=len(evaluated) / case_denominator,
        error_localization_rate=(
            sum(result.localization_correct for result in evaluated)
            / evaluated_denominator
        ),
        repair_success_rate=(
            sum(result.repair_succeeded for result in evaluated)
            / evaluated_denominator
        ),
        post_fix_test_pass_rate=(
            sum(result.post_fix_tests_passed for result in evaluated)
            / evaluated_denominator
        ),
        unrelated_change_rate=unrelated_lines / total_lines if total_lines else 0,
        mean_patch_attempts=(
            sum(result.patch_attempts for result in evaluated) / evaluated_denominator
        ),
        total_model_calls=sum(result.model_calls for result in results),
        total_tool_calls=sum(result.tool_calls for result in results),
        total_wall_time_seconds=sum(result.wall_time_seconds for result in results),
        total_input_tokens=sum(result.input_tokens for result in results),
        total_output_tokens=sum(result.output_tokens for result in results),
        total_model_cost_usd=sum(known_costs) if known_costs else None,
        safety_invariants_passed=bool(evaluated)
        and all(result.safety_invariants_passed for result in evaluated),
    )


def render_real_benchmark_markdown(
    summary: RealBenchmarkSummary, results: list[RealCaseResult]
) -> str:
    cost = (
        f"${summary.total_model_cost_usd:.4f}"
        if summary.total_model_cost_usd is not None
        else "unknown"
    )
    lines = [
        "# ReproPilot Real-Project Agent Benchmark",
        "",
        "> Infrastructure failures are excluded from Agent localization and repair rates; "
        "they remain visible in acquisition and completion metrics.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Cases | {summary.case_count} |",
        f"| Evaluated Agent cases | {summary.evaluated_case_count} |",
        f"| Infrastructure failures | {summary.infrastructure_failure_count} |",
        f"| Acquisition success rate | {summary.acquisition_success_rate:.1%} |",
        f"| Benchmark completion rate | {summary.benchmark_completion_rate:.1%} |",
        f"| Error localization rate | {summary.error_localization_rate:.1%} |",
        f"| Repair success rate | {summary.repair_success_rate:.1%} |",
        f"| Post-fix test pass rate | {summary.post_fix_test_pass_rate:.1%} |",
        f"| Unrelated changed-line rate | {summary.unrelated_change_rate:.1%} |",
        f"| Model calls | {summary.total_model_calls} |",
        f"| Tool calls | {summary.total_tool_calls} |",
        f"| Tokens | {summary.total_input_tokens + summary.total_output_tokens} |",
        f"| Model cost | {cost} |",
        "",
        "| Case | Status | Localized | Repaired | Tests |",
        "|---|---|---:|---:|---:|",
    ]
    lines.extend(
        "| "
        + " | ".join(
            [
                result.case_id,
                result.status,
                "yes" if result.localization_correct else "no",
                "yes" if result.repair_succeeded else "no",
                "yes" if result.post_fix_tests_passed else "no",
            ]
        )
        + " |"
        for result in results
    )
    return "\n".join(lines) + "\n"


def render_real_benchmark_html(
    summary: RealBenchmarkSummary, results: list[RealCaseResult]
) -> str:
    rows = "".join(
        "<tr>"
        f"<td>{escape(result.case_id)}</td>"
        f"<td>{escape(result.status)}</td>"
        f"<td>{'yes' if result.localization_correct else 'no'}</td>"
        f"<td>{'yes' if result.repair_succeeded else 'no'}</td>"
        f"<td>{'yes' if result.post_fix_tests_passed else 'no'}</td>"
        "</tr>"
        for result in results
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>ReproPilot Benchmark</title>
<style>body{{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;color:#172033}}
table{{border-collapse:collapse;width:100%;margin:20px 0}}
th,td{{border:1px solid #ccd3df;padding:8px;text-align:left}}
.metric{{display:inline-block;padding:12px;margin:4px;background:#eef3ff;border-radius:8px}}</style></head>
<body><h1>ReproPilot Real-Project Agent Benchmark</h1>
<p>Infrastructure failures are excluded from Agent rates and reported separately.</p>
<div class="metric">Repair success rate: {summary.repair_success_rate:.1%}</div>
<div class="metric">Localization rate: {summary.error_localization_rate:.1%}</div>
<div class="metric">Completion rate: {summary.benchmark_completion_rate:.1%}</div>
<table><thead><tr><th>Case</th><th>Status</th><th>Localized</th><th>Repaired</th><th>Tests</th></tr></thead>
<tbody>{rows}</tbody></table></body></html>"""


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
        function: Callable[[str], object],
        target: str,
        _error: tuple[type[BaseException], BaseException, TracebackType],
    ) -> None:
        os.chmod(target, stat.S_IWRITE)
        function(target)

    shutil.rmtree(path, onerror=clear_read_only)
