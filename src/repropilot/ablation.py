from __future__ import annotations

import html
import json
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import yaml
from pydantic import BaseModel, Field

from repropilot.benchmark import changed_lines_from_diff
from repropilot.diagnosis import diagnose_failure
from repropilot.domain import Diagnosis, DiagnosisCategory, ModelUsage, PatchProposal
from repropilot.policy import assess_patch
from repropilot.real_benchmark import InjectionError, ProbeResult, ProbeSpec
from repropilot.repair_memory import (
    NullRepairMemory,
    RepairExperience,
    RepairMemory,
    build_repair_context,
)


class AblationArm(StrEnum):
    SINGLE_TURN_RAW = "single_turn_raw"
    DIAGNOSIS_SINGLE_TURN = "diagnosis_single_turn"
    FEEDBACK_LOOP = "feedback_loop"
    EPISODIC_MEMORY = "episodic_memory"


class ProgressiveStage(BaseModel):
    id: str = Field(min_length=1)
    category: DiagnosisCategory
    root_cause: str = Field(min_length=1)
    injection: Path
    probe: ProbeSpec


class ProgressiveCase(BaseModel):
    id: str = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    commit_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    license: str = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)
    stages: list[ProgressiveStage] = Field(min_length=2)


@dataclass(frozen=True)
class AblationPatchRequest:
    arm: AblationArm
    case_id: str
    stage: ProgressiveStage
    diagnosis: Diagnosis | None
    context: str


class AblationPatchGenerator(Protocol):
    usage: list[ModelUsage]

    def propose(
        self, request: AblationPatchRequest, worktree: Path
    ) -> PatchProposal: ...


@dataclass(frozen=True)
class AblationCaseResult:
    case_id: str
    passed_stages: int
    total_stages: int
    complete_success: bool
    scope_compliant: bool
    patch_attempts: int
    model_calls: int
    total_tokens: int
    wall_time_seconds: float
    unrelated_changed_lines: int = 0
    total_changed_lines: int = 0
    memory_hits: int = 0
    status: str = "completed"
    final_failure: str | None = None
    patch_diffs: tuple[str, ...] = ()


@dataclass(frozen=True)
class AblationRunResult:
    arm: AblationArm
    repetition: int
    cases: tuple[AblationCaseResult, ...]


@dataclass(frozen=True)
class ArmAggregate:
    arm: AblationArm
    case_count: int
    complete_successes: int
    passed_stages: int
    total_stages: int
    safe_completions: int
    model_calls: int
    total_tokens: int
    wall_time_seconds: float
    patch_attempts: int
    unrelated_changed_lines: int
    total_changed_lines: int
    memory_hits: int

    @property
    def complete_success_rate(self) -> float:
        return self.complete_successes / self.case_count if self.case_count else 0.0

    @property
    def stage_resolution_rate(self) -> float:
        return self.passed_stages / self.total_stages if self.total_stages else 0.0

    @property
    def safe_completion_rate(self) -> float:
        return self.safe_completions / self.case_count if self.case_count else 0.0

    @property
    def unrelated_change_rate(self) -> float:
        if not self.total_changed_lines:
            return 0.0
        return self.unrelated_changed_lines / self.total_changed_lines


@dataclass(frozen=True)
class AblationSummary:
    by_arm: dict[AblationArm, ArmAggregate]
    deltas: dict[str, float]


def load_ablation_manifest(path: Path, *, root: Path | None = None) -> list[ProgressiveCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError("ablation manifest requires schema_version: 1")
    if not isinstance(raw.get("cases"), list):
        raise ValueError("ablation manifest requires a cases list")
    base = root or path.parent.parent
    cases = [ProgressiveCase.model_validate(item) for item in raw["cases"]]
    ids = [case.id for case in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("ablation case IDs must be unique")
    return [
        case.model_copy(
            update={
                "stages": [
                    stage.model_copy(update={"injection": (base / stage.injection).resolve()})
                    for stage in case.stages
                ]
            }
        )
        for case in cases
    ]


def run_stage_probe(stage: ProgressiveStage, workspace: Path) -> ProbeResult:
    root = workspace.resolve()
    candidate = (root / stage.probe.path).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise InjectionError(
            f"Probe path is missing or escapes workspace: {stage.probe.path}"
        )
    content = candidate.read_text(encoding="utf-8", errors="replace")
    passed = True
    if stage.probe.required_text is not None:
        passed = (
            content.count(stage.probe.required_text) == stage.probe.expected_occurrences
        )
    if stage.probe.forbidden_text is not None and stage.probe.forbidden_text in content:
        passed = False
    return ProbeResult(
        passed=passed,
        related_file=stage.probe.path,
        output="probe passed" if passed else stage.probe.failure_message,
    )


def prepare_progressive_case(case: ProgressiveCase, workspace: Path) -> int:
    for stage in case.stages:
        baseline = run_stage_probe(stage, workspace)
        if not baseline.passed:
            raise InjectionError(
                f"Pinned baseline failed {stage.id} probe: {baseline.output}"
            )
    tool_calls = len(case.stages)
    for stage in case.stages:
        checked = _apply_patch(workspace, stage.injection, check_only=True)
        tool_calls += 1
        if checked.returncode != 0:
            raise InjectionError(
                f"Injection patch does not apply for {stage.id}: {checked.stderr.strip()}"
            )
        applied = _apply_patch(workspace, stage.injection)
        tool_calls += 1
        if applied.returncode != 0:
            raise InjectionError(
                f"Injection patch failed for {stage.id}: {applied.stderr.strip()}"
            )
    if evaluate_current_stage(case, workspace)[0] is None:
        raise InjectionError(f"Combined injections did not break any probe for {case.id}")
    return tool_calls + 1


def evaluate_current_stage(
    case: ProgressiveCase, workspace: Path
) -> tuple[int | None, ProbeResult | None]:
    for index, stage in enumerate(case.stages):
        result = run_stage_probe(stage, workspace)
        if not result.passed:
            return index, result
    return None, None


def run_ablation_case(
    case: ProgressiveCase,
    workspace: Path,
    patch_generator: AblationPatchGenerator,
    *,
    arm: AblationArm,
    repair_memory: RepairMemory | None = None,
    max_attempts: int = 3,
    approve_high_risk: bool = False,
) -> AblationCaseResult:
    started = time.monotonic()
    memory = repair_memory or NullRepairMemory()
    prepare_progressive_case(case, workspace)
    allowed_attempts = 1 if arm in {
        AblationArm.SINGLE_TURN_RAW,
        AblationArm.DIAGNOSIS_SINGLE_TURN,
    } else max_attempts
    if allowed_attempts < 1 or allowed_attempts > 3:
        raise ValueError("max_attempts must be between 1 and 3")

    usage_start = len(patch_generator.usage)
    patch_diffs: list[str] = []
    failed_diffs: list[str] = []
    previous_patch: str | None = None
    verification_failure: str | None = None
    rollback_complete = False
    memory_hits = 0
    scope_compliant = True
    status = "completed"
    final_failure: str | None = None

    for _attempt in range(1, allowed_attempts + 1):
        current_index, probe = evaluate_current_stage(case, workspace)
        if current_index is None or probe is None:
            break
        stage = case.stages[current_index]
        diagnosis = None
        if arm is not AblationArm.SINGLE_TURN_RAW:
            diagnosis = diagnose_failure(
                ["semantic-probe"], probe.output, case.allowed_paths
            )
        experiences: tuple[RepairExperience, ...] = ()
        if arm is AblationArm.EPISODIC_MEMORY and diagnosis is not None:
            experiences = memory.retrieve(
                diagnosis,
                repository_url=case.repository_url,
                commit_sha=case.commit_sha,
                top_k=2,
            )
            memory_hits += len(experiences)
        context = build_repair_context(
            current_failure=probe.output,
            diagnosis=diagnosis,
            allowed_paths=tuple(case.allowed_paths),
            previous_patch=previous_patch,
            verification_failure=verification_failure,
            rollback_complete=rollback_complete,
            experiences=experiences,
        )
        request = AblationPatchRequest(
            arm=arm,
            case_id=case.id,
            stage=stage,
            diagnosis=diagnosis,
            context=context,
        )
        rollback_complete = False
        try:
            proposal = patch_generator.propose(request, workspace)
        except (RuntimeError, ValueError) as exc:
            final_failure = str(exc)
            status = "model_failed"
            continue

        previous_patch = proposal.diff
        patch_diffs.append(proposal.diff)
        changes = changed_lines_from_diff(proposal.diff)
        if any(path not in case.allowed_paths for path in changes):
            scope_compliant = False
            final_failure = "patch changed a path outside the case allowlist"
            status = "unsafe_patch"
            break
        decision = assess_patch(
            proposal.diff,
            diagnosis or _unknown_diagnosis(probe.output, case.allowed_paths),
        )
        if decision.requires_approval and not approve_high_risk:
            status = "approval_required"
            final_failure = "; ".join(decision.reasons)
            break
        checked = _apply_text_patch(workspace, proposal.diff, check_only=True)
        if checked.returncode != 0:
            failed_diffs.append(proposal.diff)
            verification_failure = checked.stderr.strip() or "patch did not apply"
            final_failure = verification_failure
            continue
        applied = _apply_text_patch(workspace, proposal.diff)
        if applied.returncode != 0:
            failed_diffs.append(proposal.diff)
            verification_failure = applied.stderr.strip() or "patch application failed"
            final_failure = verification_failure
            continue
        next_index, next_probe = evaluate_current_stage(case, workspace)
        if next_index is None:
            final_failure = None
            break
        if next_index > current_index:
            verification_failure = next_probe.output if next_probe else None
            final_failure = verification_failure
            continue

        rolled_back = _apply_text_patch(workspace, proposal.diff, reverse=True)
        if rolled_back.returncode != 0:
            raise RuntimeError(f"Patch rollback failed: {rolled_back.stderr.strip()}")
        failed_diffs.append(proposal.diff)
        rollback_complete = True
        verification_failure = next_probe.output if next_probe else probe.output
        final_failure = verification_failure

    remaining_index, remaining_probe = evaluate_current_stage(case, workspace)
    passed_stages = remaining_index if remaining_index is not None else len(case.stages)
    complete = remaining_index is None and scope_compliant
    if not complete and final_failure is None and remaining_probe is not None:
        final_failure = remaining_probe.output
    if complete and patch_diffs:
        first_stage = case.stages[0]
        diagnosis = diagnose_failure(
            ["semantic-probe"], first_stage.probe.failure_message, case.allowed_paths
        )
        observed_usage = patch_generator.usage[usage_start:]
        model = observed_usage[-1].model if observed_usage else "unknown"
        memory.record_verified(
            RepairExperience(
                id=f"{case.id}-{arm.value}-{len(patch_diffs)}",
                category=diagnosis.category.value,
                error_signature=first_stage.probe.failure_message,
                stack_tags=tuple(case.allowed_paths),
                root_cause=first_stage.root_cause,
                failed_diffs=tuple(failed_diffs),
                verified_diff="\n".join(patch_diffs),
                probe_summary=f"{len(case.stages)}/{len(case.stages)} stages passed",
                repository_url=case.repository_url,
                commit_sha=case.commit_sha,
                model=model,
                created_at=f"{time.time_ns():020d}",
            )
        )

    observed_usage = patch_generator.usage[usage_start:]
    all_changes: dict[str, set[int]] = {}
    for diff in patch_diffs:
        for path, lines in changed_lines_from_diff(diff).items():
            all_changes.setdefault(path, set()).update(lines)
    total_changed = sum(len(lines) for lines in all_changes.values())
    unrelated = sum(
        len(lines) for path, lines in all_changes.items() if path not in case.allowed_paths
    )
    if not complete and status == "completed":
        status = "failed"
    return AblationCaseResult(
        case_id=case.id,
        passed_stages=passed_stages,
        total_stages=len(case.stages),
        complete_success=complete,
        scope_compliant=scope_compliant,
        patch_attempts=len(patch_diffs),
        model_calls=len(observed_usage) if observed_usage else len(patch_diffs),
        total_tokens=sum(u.input_tokens + u.output_tokens for u in observed_usage),
        wall_time_seconds=time.monotonic() - started,
        unrelated_changed_lines=unrelated,
        total_changed_lines=total_changed,
        memory_hits=memory_hits,
        status=status if not complete else "completed",
        final_failure=final_failure,
        patch_diffs=tuple(patch_diffs),
    )


def aggregate_ablation(runs: list[AblationRunResult]) -> AblationSummary:
    by_arm: dict[AblationArm, ArmAggregate] = {}
    for arm in AblationArm:
        cases = [case for run in runs if run.arm is arm for case in run.cases]
        if not cases:
            continue
        by_arm[arm] = ArmAggregate(
            arm=arm,
            case_count=len(cases),
            complete_successes=sum(case.complete_success for case in cases),
            passed_stages=sum(case.passed_stages for case in cases),
            total_stages=sum(case.total_stages for case in cases),
            safe_completions=sum(
                case.complete_success and case.scope_compliant for case in cases
            ),
            model_calls=sum(case.model_calls for case in cases),
            total_tokens=sum(case.total_tokens for case in cases),
            wall_time_seconds=sum(case.wall_time_seconds for case in cases),
            patch_attempts=sum(case.patch_attempts for case in cases),
            unrelated_changed_lines=sum(case.unrelated_changed_lines for case in cases),
            total_changed_lines=sum(case.total_changed_lines for case in cases),
            memory_hits=sum(case.memory_hits for case in cases),
        )
    deltas: dict[str, float] = {}
    baseline = by_arm.get(AblationArm.SINGLE_TURN_RAW)
    if baseline is not None:
        for arm in (AblationArm.DIAGNOSIS_SINGLE_TURN, AblationArm.FEEDBACK_LOOP):
            value = by_arm.get(arm)
            if value is not None:
                deltas[f"{arm.value}_vs_single_turn_raw"] = (
                    value.complete_success_rate - baseline.complete_success_rate
                ) * 100
    feedback = by_arm.get(AblationArm.FEEDBACK_LOOP)
    memory = by_arm.get(AblationArm.EPISODIC_MEMORY)
    if feedback is not None and memory is not None:
        deltas["episodic_memory_vs_feedback_loop"] = (
            memory.complete_success_rate - feedback.complete_success_rate
        ) * 100
    return AblationSummary(by_arm=by_arm, deltas=deltas)


def ablation_payload(
    runs: list[AblationRunResult],
    summary: AblationSummary,
    *,
    fixture_mode: bool,
    metadata: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "fixture_mode": fixture_mode,
        "metadata": metadata,
        "summary": {
            "by_arm": {
                arm.value: {**asdict(value), "arm": arm.value}
                for arm, value in summary.by_arm.items()
            },
            "deltas_percentage_points": summary.deltas,
        },
        "runs": [
            {
                "arm": run.arm.value,
                "repetition": run.repetition,
                "cases": [asdict(case) for case in run.cases],
            }
            for run in runs
        ],
    }


def render_ablation_markdown(summary: AblationSummary, *, fixture_mode: bool) -> str:
    lines = ["# ReproPilot Agent Ablation", ""]
    if fixture_mode:
        lines.extend(
            ["> **FIXTURE MODE — framework validation only, not performance evidence.**", ""]
        )
    lines.extend(
        [
            "| Arm | Complete task success | Stage resolution | Safe completion "
            "| Model calls | Tokens |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for arm in AblationArm:
        value = summary.by_arm.get(arm)
        if value is None:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    arm.value,
                    _ratio(value.complete_successes, value.case_count),
                    _ratio(value.passed_stages, value.total_stages),
                    _ratio(value.safe_completions, value.case_count),
                    str(value.model_calls),
                    str(value.total_tokens),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Observed deltas", ""])
    if not summary.deltas:
        lines.append("No paired delta is available.")
    else:
        for name, delta_value in summary.deltas.items():
            lines.append(f"- `{name}`: {delta_value:+.1f} percentage points")
    lines.extend(
        [
            "",
            "> These are Agent task-success metrics, not model classification accuracy.",
        ]
    )
    return "\n".join(lines) + "\n"


def render_ablation_html(summary: AblationSummary, *, fixture_mode: bool) -> str:
    markdown = render_ablation_markdown(summary, fixture_mode=fixture_mode)
    rows = []
    for arm in AblationArm:
        value = summary.by_arm.get(arm)
        if value is None:
            continue
        rows.append(
            "<tr>"
            f"<td>{html.escape(arm.value)}</td>"
            f"<td>{_ratio(value.complete_successes, value.case_count)}</td>"
            f"<td>{_ratio(value.passed_stages, value.total_stages)}</td>"
            f"<td>{value.model_calls}</td><td>{value.total_tokens}</td>"
            "</tr>"
        )
    banner = (
        '<p class="fixture">FIXTURE MODE — not performance evidence</p>'
        if fixture_mode
        else ""
    )
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>ReproPilot Agent Ablation</title>"
        "<style>body{font-family:system-ui;max-width:960px;margin:40px auto;padding:0 20px}"
        "table{border-collapse:collapse;width:100%}th,td{border:1px solid #ccc;padding:8px}"
        ".fixture{background:#ffe8a3;padding:12px;font-weight:700}</style></head><body>"
        f"{banner}<h1>ReproPilot Agent Ablation</h1>"
        "<p>Agent task success — this is not model classification accuracy.</p>"
        "<table><thead><tr><th>Arm</th><th>Complete success</th>"
        "<th>Stage resolution</th><th>Model calls</th><th>Tokens</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        f"<pre>{html.escape(markdown)}</pre></body></html>"
    )


def write_ablation_reports(
    output: Path,
    runs: list[AblationRunResult],
    summary: AblationSummary,
    *,
    fixture_mode: bool,
    metadata: dict[str, object],
) -> None:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    output.mkdir(parents=True)
    payload = ablation_payload(runs, summary, fixture_mode=fixture_mode, metadata=metadata)
    (output / "ablation-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "ablation-summary.md").write_text(
        render_ablation_markdown(summary, fixture_mode=fixture_mode), encoding="utf-8"
    )
    (output / "ablation-report.html").write_text(
        render_ablation_html(summary, fixture_mode=fixture_mode), encoding="utf-8"
    )


def reverse_unified_diff(diff: str) -> str:
    reversed_lines: list[str] = []
    hunk_pattern = re.compile(
        r"^@@ -(\d+(?:,\d+)?) \+(\d+(?:,\d+)?) @@(.*?)(\r?\n)?$"
    )
    for line in diff.splitlines(keepends=True):
        match = hunk_pattern.match(line)
        if match:
            newline = match.group(4) or ""
            reversed_lines.append(
                f"@@ -{match.group(2)} +{match.group(1)} @@{match.group(3)}{newline}"
            )
        elif line.startswith(("+++", "---")):
            reversed_lines.append(line)
        elif line.startswith("+"):
            reversed_lines.append("-" + line[1:])
        elif line.startswith("-"):
            reversed_lines.append("+" + line[1:])
        else:
            reversed_lines.append(line)
    return "".join(reversed_lines)


def _ratio(numerator: int, denominator: int) -> str:
    percentage = numerator / denominator * 100 if denominator else 0.0
    return f"{numerator}/{denominator} ({percentage:.1f}%)"


def _unknown_diagnosis(failure: str, allowed_paths: list[str]) -> Diagnosis:
    return Diagnosis(
        category=DiagnosisCategory.UNKNOWN,
        root_cause="Raw single-turn baseline; no structured diagnosis supplied.",
        evidence=[failure],
        related_files=allowed_paths,
        confidence=0,
    )


def _apply_patch(
    workspace: Path,
    patch: Path,
    *,
    check_only: bool = False,
    reverse: bool = False,
) -> subprocess.CompletedProcess[str]:
    argv = ["git", "apply", "--whitespace=nowarn", "--unidiff-zero"]
    if check_only:
        argv.append("--check")
    if reverse:
        argv.append("--reverse")
    argv.append(str(patch))
    return subprocess.run(
        argv, cwd=workspace, capture_output=True, text=True, check=False
    )


def _apply_text_patch(
    workspace: Path,
    diff: str,
    *,
    check_only: bool = False,
    reverse: bool = False,
) -> subprocess.CompletedProcess[str]:
    argv = ["git", "apply", "--whitespace=nowarn", "--unidiff-zero"]
    if check_only:
        argv.append("--check")
    if reverse:
        argv.append("--reverse")
    argv.append("-")
    completed = subprocess.run(
        argv,
        cwd=workspace,
        input=diff.replace("\r\n", "\n").encode("utf-8"),
        capture_output=True,
        check=False,
    )
    return subprocess.CompletedProcess(
        completed.args,
        completed.returncode,
        completed.stdout.decode("utf-8", errors="replace"),
        completed.stderr.decode("utf-8", errors="replace"),
    )
