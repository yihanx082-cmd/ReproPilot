from __future__ import annotations

from pathlib import Path

import pytest

from repropilot.benchmark import (
    BenchmarkCase,
    CaseObservation,
    aggregate_results,
    evaluate_case,
    load_cases,
    run_reference_case,
)


def _case() -> BenchmarkCase:
    return BenchmarkCase(
        id="missing-dependency",
        fixture=Path("benchmark/fixtures/yaml_project"),
        injection=Path("benchmark/injections/missing_dependency.patch"),
        expected_category="dependency",
        expected_root_cause="A required Python package is missing.",
        allowed_paths=["train.py"],
        expected_outcome="auto_fix",
    )


def test_unrelated_change_rate_uses_changed_lines_outside_allowed_scope() -> None:
    result = evaluate_case(
        _case(),
        CaseObservation(
            diagnosed_category="dependency",
            changed_lines={"train.py": {10}, "README.md": {1}},
            repair_succeeded=True,
            post_fix_tests_passed=True,
            patch_attempts=1,
            model_calls=1,
            tool_calls=4,
            wall_time_seconds=2.0,
            model_cost_usd=0.01,
            approval_required=False,
        ),
    )

    assert result.unrelated_change_rate == pytest.approx(0.5)
    assert result.localization_correct is True


def test_empty_patch_has_zero_unrelated_change_rate() -> None:
    result = evaluate_case(
        _case(),
        CaseObservation(diagnosed_category="unknown", changed_lines={}),
    )

    assert result.unrelated_change_rate == 0
    assert result.localization_correct is False


def test_aggregate_metrics_are_exact() -> None:
    first = evaluate_case(
        _case(),
        CaseObservation(
            diagnosed_category="dependency",
            changed_lines={"train.py": {1}},
            repair_succeeded=True,
            post_fix_tests_passed=True,
            patch_attempts=1,
            model_calls=1,
            tool_calls=4,
            wall_time_seconds=2.0,
            model_cost_usd=0.02,
        ),
    )
    second = evaluate_case(
        _case().model_copy(update={"id": "second"}),
        CaseObservation(
            diagnosed_category="path",
            changed_lines={"README.md": {1, 2}},
            repair_succeeded=False,
            post_fix_tests_passed=False,
            patch_attempts=3,
            model_calls=2,
            tool_calls=8,
            wall_time_seconds=4.0,
            model_cost_usd=0.04,
        ),
    )

    summary = aggregate_results([first, second], mode="test")

    assert summary.error_localization_rate == 0.5
    assert summary.repair_success_rate == 0.5
    assert summary.post_fix_test_pass_rate == 0.5
    assert summary.unrelated_change_rate == pytest.approx(2 / 3)
    assert summary.mean_patch_attempts == 2
    assert summary.total_model_calls == 3
    assert summary.total_tool_calls == 12
    assert summary.total_wall_time_seconds == 6
    assert summary.total_model_cost_usd == 0.06


def test_cases_file_defines_six_unique_single_faults() -> None:
    root = Path(__file__).parents[1]
    cases = load_cases(root / "benchmark" / "cases.yaml", root=root)

    assert len(cases) == 6
    assert len({case.id for case in cases}) == 6
    assert {case.expected_category for case in cases} == {
        "dependency",
        "path",
        "configuration",
        "cuda_runtime",
        "metric",
        "data",
    }
    assert all(case.fixture.is_dir() for case in cases)
    assert all(case.injection.is_file() for case in cases)


def test_reference_baseline_runs_all_faults_without_mutating_fixtures() -> None:
    root = Path(__file__).parents[1]
    cases = load_cases(root / "benchmark" / "cases.yaml", root=root)

    results = [run_reference_case(case) for case in cases]

    assert all(result.localization_correct for result in results)
    assert all(result.repair_succeeded for result in results)
    assert all(result.post_fix_tests_passed for result in results)
    assert all(result.unrelated_change_rate == 0 for result in results)
    assert all(result.approval_gate_correct for result in results)
    assert all(result.safety_invariants_passed for result in results)
