from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Literal

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
    last_error = "unknown Git error"
    tool_calls = 0
    for attempt in range(1, retries + 1):
        if destination.exists():
            shutil.rmtree(destination)
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
        checkout = _git(["-C", str(destination), "checkout", "--detach", case.commit_sha])
        tool_calls += 1
        if checkout.returncode != 0:
            last_error = checkout.stderr.strip()
            continue
        resolved = _git(["-C", str(destination), "rev-parse", "HEAD"])
        tool_calls += 1
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
        shutil.rmtree(destination)
    raise AcquisitionError(
        f"Repository acquisition failed after {retries} attempts: {last_error}",
        attempts=retries,
    )


def _git(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *argv],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
