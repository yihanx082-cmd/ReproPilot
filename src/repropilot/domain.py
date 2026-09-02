from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue, model_validator


class DatasetRequest(BaseModel):
    name: str = Field(min_length=1)
    path: Path


class EnvironmentRequest(BaseModel):
    python: str = "3.11"
    device: Literal["cpu", "cuda", "auto"] = "cpu"


class RunLimits(BaseModel):
    wall_time_seconds: int = Field(default=1200, ge=60, le=1200)
    max_patch_attempts: int = Field(default=3, ge=0, le=3)


class FormalExperimentRequest(BaseModel):
    command: list[str] = Field(min_length=1)
    seeds: list[int] = Field(min_length=3, max_length=10)
    comparison_scope: Literal["paper", "reduced"] = "reduced"
    scope_evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_contract(self) -> FormalExperimentRequest:
        if len(set(self.seeds)) != len(self.seeds):
            raise ValueError("formal experiment seeds must be unique")
        if not any("{seed}" in token for token in self.command):
            raise ValueError("formal experiment command must contain {seed}")
        if self.comparison_scope == "paper" and not self.scope_evidence:
            raise ValueError("paper comparison scope requires evidence citations")
        return self


class RunRequest(BaseModel):
    paper: Path
    repository: str = Field(min_length=1)
    dataset: DatasetRequest
    command: list[str] = Field(min_length=1)
    formal_experiment: FormalExperimentRequest | None = None
    environment: EnvironmentRequest = Field(default_factory=EnvironmentRequest)
    limits: RunLimits = Field(default_factory=RunLimits)


class RunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    TIMED_OUT = "TIMED_OUT"


class RunState(StrEnum):
    INGEST = "INGEST"
    AUDIT = "AUDIT"
    BUILD = "BUILD"
    SMOKE_RUN = "SMOKE_RUN"
    FORMAL_EXPERIMENT = "FORMAL_EXPERIMENT"
    DIAGNOSE = "DIAGNOSE"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    APPLY_PATCH = "APPLY_PATCH"
    VERIFY = "VERIFY"
    ROLLBACK = "ROLLBACK"
    COMPARE = "COMPARE"
    SCORE = "SCORE"
    REPORT = "REPORT"


class EventKind(StrEnum):
    STATE = "state"
    COMMAND = "command"
    DIAGNOSIS = "diagnosis"
    PATCH = "patch"
    APPROVAL = "approval"
    TEST = "test"
    RESULT = "result"


class EvidenceEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    kind: EventKind
    message: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class PaperPage(BaseModel):
    page: int = Field(ge=1)
    text: str


class PaperClaim(BaseModel):
    field: str = Field(min_length=1)
    value: JsonValue
    unit: str | None = None
    evidence_text: str = Field(min_length=1)
    page: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class PaperResult(BaseModel):
    metric: str = Field(min_length=1)
    value: float
    unit: str | None = None
    evidence_text: str = Field(min_length=1)
    page: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class PaperSpec(BaseModel):
    claims: list[PaperClaim] = Field(default_factory=list)
    reported_results: list[PaperResult] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)


class ModelUsage(BaseModel):
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class PaperExtraction(BaseModel):
    spec: PaperSpec
    usage: ModelUsage


RepoExtractor = Literal["yaml", "json", "toml", "python_ast", "readme", "run_request"]


class RepoFact(BaseModel):
    field: str = Field(min_length=1)
    value: JsonValue
    source_path: str = Field(min_length=1)
    line_start: int = Field(ge=1)
    extractor: RepoExtractor


class FindingStatus(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    UNKNOWN = "unknown"


class FindingSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlignmentFinding(BaseModel):
    field: str = Field(min_length=1)
    paper_claim: PaperClaim | None = None
    repo_fact: RepoFact | None = None
    status: FindingStatus
    severity: FindingSeverity
    explanation: str = Field(min_length=1)


class CommandResult(BaseModel):
    exit_code: int
    stdout_path: Path
    stderr_path: Path
    duration_seconds: float = Field(ge=0)
    timed_out: bool = False
    argv: list[str] = Field(default_factory=list)
    image_digest: str | None = None
    dockerfile_sha256: str | None = None


class DiagnosisCategory(StrEnum):
    DEPENDENCY = "dependency"
    PATH = "path"
    CONFIGURATION = "configuration"
    CUDA_RUNTIME = "cuda_runtime"
    DATA = "data"
    METRIC = "metric"
    UNKNOWN = "unknown"


class Diagnosis(BaseModel):
    category: DiagnosisCategory
    root_cause: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    related_files: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)


class RiskLevel(StrEnum):
    LOW = "low"
    HIGH = "high"


class PatchProposal(BaseModel):
    diff: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    risk: RiskLevel
    targeted_test: list[str] = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)


class ApprovalDecision(BaseModel):
    patch_id: str = Field(min_length=1)
    patch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved: bool
    reason: str | None = None


class RunSummary(BaseModel):
    run_dir: Path
    status: RunStatus
    states: list[RunState]
    attempts: int = Field(ge=0)
    reason: str | None = None


class EvidenceStatus(StrEnum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ReproductionLabel(StrEnum):
    REPRODUCED = "REPRODUCED"
    PARTIAL = "PARTIAL"
    PROVISIONAL_SMOKE_RUN = "PROVISIONAL_SMOKE_RUN"
    NOT_REPRODUCED = "NOT_REPRODUCED"


class DimensionEvidence(BaseModel):
    status: EvidenceStatus
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_evidence_for_earned_status(self) -> DimensionEvidence:
        if self.status in {EvidenceStatus.VERIFIED, EvidenceStatus.PARTIAL} and not self.evidence:
            raise ValueError("verified or partial evidence requires at least one artifact ID")
        return self


class MetricComparison(BaseModel):
    name: str = Field(min_length=1)
    paper_value: float
    run_values: list[float] = Field(min_length=1)
    delta: float
    mean: float
    std: float = Field(ge=0)
    comparable: bool
    evidence: list[str] = Field(default_factory=list)


class ScoreDimension(BaseModel):
    name: str = Field(min_length=1)
    weight: int = Field(gt=0)
    earned: float = Field(ge=0)
    status: EvidenceStatus
    evidence: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_earned_score(self) -> ScoreDimension:
        if self.earned > self.weight:
            raise ValueError("earned score cannot exceed dimension weight")
        if self.earned > 0 and not self.evidence:
            raise ValueError("earned score requires at least one artifact ID")
        return self


class RepairAttempt(BaseModel):
    diagnosis: Diagnosis | None = None
    patch: PatchProposal | None = None
    approval: ApprovalDecision | None = None
    test_result: CommandResult | None = None


class FormalSeedEvidence(BaseModel):
    seed: int
    artifact: str = Field(min_length=1)
    argv: list[str] = Field(min_length=1)
    exit_code: int
    timed_out: bool = False
    duration_seconds: float = Field(ge=0)
    image_digest: str | None = None
    dockerfile_sha256: str | None = None


class FormalExperimentEvidence(BaseModel):
    comparison_scope: Literal["paper", "reduced"]
    scope_evidence: list[str] = Field(default_factory=list)
    results: list[FormalSeedEvidence] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    environment: DimensionEvidence
    data: DimensionEvidence
    configuration: DimensionEvidence
    metrics: DimensionEvidence
    random_seeds: DimensionEvidence
    result_proximity: DimensionEvidence
    external_dependencies: DimensionEvidence
    metric_comparisons: list[MetricComparison] = Field(default_factory=list)
    execution_succeeded: bool = True
    evidence_complete: bool = True
    dataset_subset: bool = False
    epoch_count_differs: bool = False
    model_differs: bool = False
    status: RunStatus | None = None
    terminal_reason: str | None = None
    paper_source: str | None = None
    repository_source: str | None = None
    dataset_source: str | None = None
    alignment_findings: list[AlignmentFinding] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    repair_attempts: list[RepairAttempt] = Field(default_factory=list)
    duration_seconds: float | None = Field(default=None, ge=0)
    model_usage: list[ModelUsage] = Field(default_factory=list)
    formal_experiment: FormalExperimentEvidence | None = None
    unresolved_risks: list[str] = Field(default_factory=list)


class ReproScore(BaseModel):
    total: float = Field(ge=0, le=100)
    label: ReproductionLabel
    dimensions: list[ScoreDimension]
    metric_comparisons: list[MetricComparison]
    comparable: bool
    reasons: list[str] = Field(default_factory=list)
