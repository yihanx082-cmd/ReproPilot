from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field


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
