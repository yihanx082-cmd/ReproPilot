from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, JsonValue


class DatasetRequest(BaseModel):
    name: str = Field(min_length=1)
    path: Path


class EnvironmentRequest(BaseModel):
    python: str = "3.11"
    device: Literal["cpu", "cuda", "auto"] = "cpu"


class RunLimits(BaseModel):
    wall_time_seconds: int = Field(default=1200, ge=60, le=1200)
    max_patch_attempts: int = Field(default=3, ge=0, le=3)


class RunRequest(BaseModel):
    paper: Path
    repository: str = Field(min_length=1)
    dataset: DatasetRequest
    command: list[str] = Field(min_length=1)
    environment: EnvironmentRequest = Field(default_factory=EnvironmentRequest)
    limits: RunLimits = Field(default_factory=RunLimits)


class RunStatus(StrEnum):
    CREATED = "CREATED"


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


RepoExtractor = Literal["yaml", "json", "toml", "python_ast", "readme"]


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
