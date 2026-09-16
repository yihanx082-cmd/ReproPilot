from __future__ import annotations

import subprocess
from pathlib import Path

from repropilot.ablation import (
    AblationArm,
    AblationCaseResult,
    AblationPatchRequest,
    AblationRunResult,
    ProgressiveCase,
    aggregate_ablation,
    load_ablation_manifest,
    render_ablation_html,
    render_ablation_markdown,
    reverse_unified_diff,
    run_ablation_case,
    write_ablation_reports,
)
from repropilot.domain import ModelUsage, PatchProposal, RiskLevel


class StagePatchGenerator:
    def __init__(self, diffs: dict[str, str]) -> None:
        self.diffs = diffs
        self.requests: list[AblationPatchRequest] = []
        self.usage: list[ModelUsage] = []

    def propose(
        self, request: AblationPatchRequest, worktree: Path
    ) -> PatchProposal:
        del worktree
        self.requests.append(request)
        self.usage.append(
            ModelUsage(
                model="test-model",
                input_tokens=10,
                output_tokens=5,
                duration_seconds=0.01,
            )
        )
        return PatchProposal(
            diff=self.diffs[request.stage.id],
            explanation="repair current stage",
            risk=RiskLevel.LOW,
            targeted_test=["semantic-probe"],
            allowed_paths=["train.py"],
        )


def _commit_repository(path: Path) -> str:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "core.autocrlf", "false"], cwd=path, check=True)
    (path / "train.py").write_bytes(b"SETTING_A = 'good'\nSETTING_B = 'good'\n")
    subprocess.run(["git", "add", "train.py"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "baseline"], cwd=path, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _diff(old: str, new: str, line: int) -> str:
    return (
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        f"@@ -{line} +{line} @@\n"
        f"-{old}\n"
        f"+{new}\n"
    )


def _case(tmp_path: Path) -> tuple[ProgressiveCase, Path, dict[str, str]]:
    workspace = tmp_path / "workspace"
    commit = _commit_repository(workspace)
    injection_a = tmp_path / "a.patch"
    injection_b = tmp_path / "b.patch"
    injection_a.write_bytes(
        _diff("SETTING_A = 'good'", "SETTING_A = 'bad'", 1).encode()
    )
    injection_b.write_bytes(
        _diff("SETTING_B = 'good'", "SETTING_B = 'bad'", 2).encode()
    )
    case = ProgressiveCase(
        id="progressive",
        repository_url=str(workspace),
        commit_sha=commit,
        license="MIT",
        allowed_paths=["train.py"],
        stages=[
            {
                "id": "stage-a",
                "category": "configuration",
                "root_cause": "setting A is wrong",
                "injection": injection_a,
                "probe": {
                    "path": "train.py",
                    "required_text": "SETTING_A = 'good'",
                    "failure_message": "CONFIGURATION ERROR in train.py: setting A is bad",
                },
            },
            {
                "id": "stage-b",
                "category": "path",
                "root_cause": "setting B is wrong",
                "injection": injection_b,
                "probe": {
                    "path": "train.py",
                    "required_text": "SETTING_B = 'good'",
                    "failure_message": "FileNotFoundError in train.py: setting B is bad",
                },
            },
        ],
    )
    repairs = {
        "stage-a": _diff("SETTING_A = 'bad'", "SETTING_A = 'good'", 1),
        "stage-b": _diff("SETTING_B = 'bad'", "SETTING_B = 'good'", 2),
    }
    return case, workspace, repairs


def test_frozen_manifest_contains_three_two_stage_cases() -> None:
    root = Path(__file__).parents[1]
    cases = load_ablation_manifest(root / "benchmark" / "real-ablation.yaml", root=root)

    assert [case.id for case in cases] == [
        "convmixer-progressive",
        "resnet-progressive",
        "lightning-progressive",
    ]
    assert all(len(case.commit_sha) == 40 for case in cases)
    assert all(len(case.stages) == 2 for case in cases)
    assert all(stage.injection.is_file() for case in cases for stage in case.stages)


def test_reverse_unified_diff_swaps_hunk_ranges_without_corrupting_headers() -> None:
    original = (
        "diff --git a/train.py b/train.py\n"
        "--- a/train.py\n"
        "+++ b/train.py\n"
        "@@ -1,3 +1,4 @@\n"
        "+import missing\n"
        " import torch\n"
    )

    reversed_diff = reverse_unified_diff(original)

    assert "--- a/train.py\n+++ b/train.py" in reversed_diff
    assert "@@ -1,4 +1,3 @@" in reversed_diff
    assert "-import missing" in reversed_diff


def test_single_turn_resolves_one_stage_but_feedback_loop_resolves_both(
    tmp_path: Path,
) -> None:
    case, workspace, repairs = _case(tmp_path)
    single = StagePatchGenerator(repairs)

    single_result = run_ablation_case(
        case, workspace, single, arm=AblationArm.DIAGNOSIS_SINGLE_TURN
    )

    assert single_result.passed_stages == 1
    assert single_result.complete_success is False
    assert single_result.model_calls == 1

    subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=workspace, check=True)
    loop = StagePatchGenerator(repairs)
    loop_result = run_ablation_case(
        case, workspace, loop, arm=AblationArm.FEEDBACK_LOOP
    )

    assert loop_result.passed_stages == 2
    assert loop_result.complete_success is True
    assert loop_result.model_calls == 2
    assert "PREVIOUS_PATCH" in loop.requests[1].context
    assert "SETTING_A = 'bad'" in loop.requests[1].context
    assert "setting B is bad" in loop.requests[1].context


def test_unsafe_patch_stops_without_touching_unrelated_file(tmp_path: Path) -> None:
    case, workspace, repairs = _case(tmp_path)
    bad = dict(repairs)
    bad["stage-a"] = (
        "diff --git a/other.py b/other.py\n"
        "new file mode 100644\n"
        "--- /dev/null\n"
        "+++ b/other.py\n"
        "@@ -0,0 +1 @@\n"
        "+unsafe = True\n"
    )

    result = run_ablation_case(
        case, workspace, StagePatchGenerator(bad), arm=AblationArm.FEEDBACK_LOOP
    )

    assert result.status == "unsafe_patch"
    assert result.scope_compliant is False
    assert not (workspace / "other.py").exists()


def test_aggregation_and_reports_show_counts_and_percentage_points(tmp_path: Path) -> None:
    runs = [
        AblationRunResult(
            arm=AblationArm.SINGLE_TURN_RAW,
            repetition=1,
            cases=(AblationCaseResult("c1", 1, 2, False, True, 1, 1, 15, 1.0),),
        ),
        AblationRunResult(
            arm=AblationArm.FEEDBACK_LOOP,
            repetition=1,
            cases=(AblationCaseResult("c1", 2, 2, True, True, 2, 2, 30, 2.0),),
        ),
    ]

    summary = aggregate_ablation(runs)
    markdown = render_ablation_markdown(summary, fixture_mode=True)
    rendered_html = render_ablation_html(summary, fixture_mode=True)

    assert summary.by_arm[AblationArm.SINGLE_TURN_RAW].complete_successes == 0
    assert summary.by_arm[AblationArm.FEEDBACK_LOOP].complete_successes == 1
    assert summary.deltas["feedback_loop_vs_single_turn_raw"] == 100.0
    assert "1/1 (100.0%)" in markdown
    assert "percentage points" in markdown
    assert "not model classification accuracy" in rendered_html
    assert "FIXTURE MODE" in rendered_html

    output = tmp_path / "report"
    write_ablation_reports(
        output,
        runs,
        summary,
        fixture_mode=True,
        metadata={"git_commit": "a" * 40},
    )
    assert (output / "ablation-results.json").is_file()
    assert (output / "ablation-summary.md").is_file()
    assert (output / "ablation-report.html").is_file()
