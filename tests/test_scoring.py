from __future__ import annotations

import pytest
from pydantic import ValidationError

from repropilot.domain import (
    DimensionEvidence,
    EvidenceBundle,
    EvidenceStatus,
    MetricComparison,
    ReproductionLabel,
)
from repropilot.scoring import (
    SCORE_WEIGHTS,
    compare_metric,
    result_proximity_evidence,
    score_reproduction,
)


def _dimension(status: EvidenceStatus, artifact: str) -> DimensionEvidence:
    return DimensionEvidence(status=status, evidence=[artifact])


def _bundle(**overrides: object) -> EvidenceBundle:
    values: dict[str, object] = {
        "environment": _dimension(EvidenceStatus.VERIFIED, "environment.json"),
        "data": _dimension(EvidenceStatus.VERIFIED, "data_audit.json"),
        "configuration": _dimension(EvidenceStatus.VERIFIED, "alignment.json"),
        "metrics": _dimension(EvidenceStatus.VERIFIED, "metrics.json"),
        "random_seeds": _dimension(EvidenceStatus.VERIFIED, "seeds.json"),
        "result_proximity": _dimension(EvidenceStatus.VERIFIED, "comparison.json"),
        "external_dependencies": _dimension(EvidenceStatus.VERIFIED, "dependencies.json"),
        "metric_comparisons": [
            compare_metric("macro_f1", paper_value=0.90, run_values=[0.89, 0.90, 0.91])
        ],
    }
    values.update(overrides)
    return EvidenceBundle.model_validate(values)


def test_fixed_weights_total_100_and_verified_evidence_earns_full_score() -> None:
    result = score_reproduction(_bundle())

    assert sum(SCORE_WEIGHTS.values()) == 100
    assert result.total == 100
    assert result.label == ReproductionLabel.REPRODUCED
    assert all(dimension.evidence for dimension in result.dimensions)


def test_partial_evidence_earns_half_weight_and_unknown_earns_zero() -> None:
    result = score_reproduction(
        _bundle(
            environment=_dimension(EvidenceStatus.PARTIAL, "environment.json"),
            external_dependencies=DimensionEvidence(status=EvidenceStatus.UNKNOWN),
        )
    )

    dimensions = {dimension.name: dimension for dimension in result.dimensions}
    assert dimensions["environment"].earned == 7.5
    assert dimensions["external_dependencies"].earned == 0
    assert dimensions["external_dependencies"].status == EvidenceStatus.UNKNOWN
    assert result.total == 87.5
    assert result.label == ReproductionLabel.REPRODUCED


@pytest.mark.parametrize("status", [EvidenceStatus.VERIFIED, EvidenceStatus.PARTIAL])
def test_earned_points_require_artifact_ids(status: EvidenceStatus) -> None:
    with pytest.raises(ValidationError, match="evidence"):
        DimensionEvidence(status=status)


@pytest.mark.parametrize(
    "reduction",
    [
        {"dataset_subset": True},
        {"epoch_count_differs": True},
        {"model_differs": True},
    ],
)
def test_reduced_experiments_are_never_claimed_as_reproduced(
    reduction: dict[str, bool],
) -> None:
    result = score_reproduction(_bundle(**reduction))
    dimensions = {dimension.name: dimension for dimension in result.dimensions}

    assert result.label == ReproductionLabel.PROVISIONAL_SMOKE_RUN
    assert result.comparable is False
    assert dimensions["result_proximity"].earned == 0
    assert all(comparison.comparable is False for comparison in result.metric_comparisons)


def test_comparable_run_below_threshold_is_partial() -> None:
    result = score_reproduction(
        _bundle(
            data=_dimension(EvidenceStatus.FAILED, "data_audit.json"),
            configuration=_dimension(EvidenceStatus.PARTIAL, "alignment.json"),
        )
    )

    assert result.total == 70
    assert result.comparable is True
    assert result.label == ReproductionLabel.PARTIAL


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"execution_succeeded": False}, "execution failed"),
        ({"evidence_complete": False}, "evidence incomplete"),
        ({"metric_comparisons": []}, "no metric comparison"),
    ],
)
def test_execution_or_evidence_failure_is_not_reproduced(
    overrides: dict[str, object], reason: str
) -> None:
    result = score_reproduction(_bundle(**overrides))

    assert result.label == ReproductionLabel.NOT_REPRODUCED
    assert reason in result.reasons


def test_metric_comparison_is_deterministic() -> None:
    comparison = compare_metric(
        "macro_f1",
        paper_value=0.90,
        run_values=[0.88, 0.89, 0.90],
    )

    assert comparison.model_copy(update={"std": 0.0}) == MetricComparison(
        name="macro_f1",
        paper_value=0.90,
        run_values=[0.88, 0.89, 0.90],
        delta=-0.01,
        mean=0.89,
        std=0.0,
        comparable=True,
        evidence=[],
    )
    assert comparison.std == pytest.approx(0.0081649658)


@pytest.mark.parametrize(
    ("paper_value", "run_value", "expected"),
    [
        (8.75, 8.27, EvidenceStatus.VERIFIED),
        (0.90, 0.872, EvidenceStatus.PARTIAL),
        (90.0, 80.0, EvidenceStatus.FAILED),
    ],
)
def test_result_proximity_uses_percentage_point_thresholds(
    paper_value: float, run_value: float, expected: EvidenceStatus
) -> None:
    comparison = compare_metric(
        "metric",
        paper_value=paper_value,
        run_values=[run_value],
        evidence=["formal-seed-11.stdout.log", "paper_spec.json"],
    )

    dimension = result_proximity_evidence(
        [comparison],
        comparable=True,
        evidence=["experiment_manifest.json", "metric_comparisons.json"],
    )

    assert dimension.status == expected
    assert dimension.evidence == ["experiment_manifest.json", "metric_comparisons.json"]


def test_result_proximity_stays_unknown_for_reduced_scope() -> None:
    comparison = compare_metric("metric", paper_value=8.75, run_values=[8.27])

    dimension = result_proximity_evidence(
        [comparison], comparable=False, evidence=["metric_comparisons.json"]
    )

    assert dimension.status == EvidenceStatus.UNKNOWN
    assert dimension.evidence == []
