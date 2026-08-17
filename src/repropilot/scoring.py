from __future__ import annotations

from statistics import fmean, pstdev

from repropilot.domain import (
    DimensionEvidence,
    EvidenceBundle,
    EvidenceStatus,
    MetricComparison,
    ReproductionLabel,
    ReproScore,
    ScoreDimension,
)

SCORE_WEIGHTS: dict[str, int] = {
    "environment": 15,
    "data": 20,
    "configuration": 20,
    "metrics": 15,
    "random_seeds": 10,
    "result_proximity": 15,
    "external_dependencies": 5,
}

_STATUS_FRACTIONS = {
    EvidenceStatus.VERIFIED: 1.0,
    EvidenceStatus.PARTIAL: 0.5,
    EvidenceStatus.FAILED: 0.0,
    EvidenceStatus.UNKNOWN: 0.0,
}


def compare_metric(
    name: str,
    *,
    paper_value: float,
    run_values: list[float],
    comparable: bool = True,
    evidence: list[str] | None = None,
) -> MetricComparison:
    if not run_values:
        raise ValueError("run_values must contain at least one result")
    mean = fmean(run_values)
    return MetricComparison(
        name=name,
        paper_value=paper_value,
        run_values=run_values,
        delta=round(mean - paper_value, 12),
        mean=mean,
        std=pstdev(run_values),
        comparable=comparable,
        evidence=evidence or [],
    )


def score_reproduction(evidence: EvidenceBundle) -> ReproScore:
    reduced = evidence.dataset_subset or evidence.epoch_count_differs or evidence.model_differs
    comparisons = [
        comparison.model_copy(update={"comparable": False})
        if reduced
        else comparison.model_copy(deep=True)
        for comparison in evidence.metric_comparisons
    ]
    comparable = bool(comparisons) and not reduced and all(
        comparison.comparable for comparison in comparisons
    )

    dimensions: list[ScoreDimension] = []
    for name, weight in SCORE_WEIGHTS.items():
        dimension = _dimension_evidence(evidence, name)
        if name == "result_proximity" and not comparable:
            dimension = DimensionEvidence(status=EvidenceStatus.UNKNOWN)
        dimensions.append(
            ScoreDimension(
                name=name,
                weight=weight,
                earned=weight * _STATUS_FRACTIONS[dimension.status],
                status=dimension.status,
                evidence=dimension.evidence,
            )
        )

    total = sum(dimension.earned for dimension in dimensions)
    reasons: list[str] = []
    if not evidence.execution_succeeded:
        reasons.append("execution failed")
    if not evidence.evidence_complete:
        reasons.append("evidence incomplete")
    if not comparisons:
        reasons.append("no metric comparison")

    if not evidence.execution_succeeded or not evidence.evidence_complete or not comparisons:
        label = ReproductionLabel.NOT_REPRODUCED
    elif reduced:
        label = ReproductionLabel.PROVISIONAL_SMOKE_RUN
    elif comparable and total >= 85:
        label = ReproductionLabel.REPRODUCED
    elif comparable:
        label = ReproductionLabel.PARTIAL
    else:
        label = ReproductionLabel.NOT_REPRODUCED

    return ReproScore(
        total=total,
        label=label,
        dimensions=dimensions,
        metric_comparisons=comparisons,
        comparable=comparable,
        reasons=reasons,
    )


def _dimension_evidence(evidence: EvidenceBundle, name: str) -> DimensionEvidence:
    value = getattr(evidence, name)
    if not isinstance(value, DimensionEvidence):
        raise TypeError(f"{name} is not dimension evidence")
    return value
