from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from repropilot.domain import Diagnosis, RiskLevel

ALLOWED_EXECUTABLES = {"python", "python3", "pytest"}
SHELL_OPERATORS = {"&", "&&", "|", "||", ";", ">", ">>", "<"}
BLOCKED_OPTIONS = {"--privileged"}


class RiskDecision(BaseModel):
    allowed: bool
    reason: str = Field(min_length=1)


class PatchAnalysis(BaseModel):
    changed_files: list[str]
    changed_lines: int = Field(ge=0)
    unsafe_operations: list[str] = Field(default_factory=list)


class PatchRiskDecision(BaseModel):
    level: RiskLevel
    requires_approval: bool
    reasons: list[str] = Field(min_length=1)
    changed_files: list[str]
    changed_lines: int = Field(ge=0)


def assess_command(argv: list[str]) -> RiskDecision:
    if not argv:
        return RiskDecision(allowed=False, reason="Command argv must not be empty.")

    executable = Path(argv[0]).name.lower().removesuffix(".exe")
    if executable not in ALLOWED_EXECUTABLES:
        return RiskDecision(
            allowed=False,
            reason=f"Executable {executable!r} is outside the MVP allowlist.",
        )

    for argument in argv[1:]:
        normalized = argument.strip().lower()
        if normalized in SHELL_OPERATORS or normalized in BLOCKED_OPTIONS:
            return RiskDecision(
                allowed=False,
                reason=f"Shell or privileged token {argument!r} is not allowed.",
            )
        if normalized.startswith(("http://", "https://")):
            return RiskDecision(
                allowed=False,
                reason="External URLs are not allowed in target commands.",
            )

    return RiskDecision(allowed=True, reason="Command uses an allowed explicit executable.")


def analyze_patch(diff: str) -> PatchAnalysis:
    changed_files: list[str] = []
    changed_lines = 0
    unsafe_operations: list[str] = []
    unsafe_markers = {
        "GIT binary patch": "binary patch",
        "Binary files ": "binary patch",
        "rename from ": "rename",
        "rename to ": "rename",
        "deleted file mode ": "file deletion",
        "new file mode 120000": "symlink",
    }

    for line in diff.splitlines():
        if line.startswith("diff --git a/"):
            parts = line.split(" b/", 1)
            if len(parts) == 2:
                path = parts[1]
                if path not in changed_files:
                    changed_files.append(path)
        elif (line.startswith("+") and not line.startswith("+++")) or (
            line.startswith("-") and not line.startswith("---")
        ):
            changed_lines += 1
        for marker, operation in unsafe_markers.items():
            if line.startswith(marker) and operation not in unsafe_operations:
                unsafe_operations.append(operation)

    return PatchAnalysis(
        changed_files=changed_files,
        changed_lines=changed_lines,
        unsafe_operations=unsafe_operations,
    )


def assess_patch(diff: str, diagnosis: Diagnosis) -> PatchRiskDecision:
    analysis = analyze_patch(diff)
    reasons: list[str] = []
    changed_text = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )
    lowered = changed_text.casefold()

    if diagnosis.category in {"data", "metric"}:
        reasons.append(f"{diagnosis.category.value} behavior can change reported results")
    semantic_markers = (
        "split_strategy",
        "patient_level",
        "f1_average",
        "average = 'macro'",
        'average = "macro"',
        "architecture",
        "pretrained_weights",
    )
    if any(marker in lowered for marker in semantic_markers):
        reasons.append("patch changes data, metric, model, or pretrained-weight semantics")
    if any(marker in lowered for marker in ("http://", "https://", "curl ", "wget ")):
        reasons.append("patch introduces an external download")
    if any(
        path.casefold().endswith((".sh", ".bat", ".cmd", ".ps1"))
        for path in analysis.changed_files
    ):
        reasons.append("patch adds or changes a shell script")
    if len(analysis.changed_files) > 3:
        reasons.append("patch changes more than 3 files")
    if analysis.changed_lines > 120:
        reasons.append("patch changes more than 120 lines")
    if analysis.unsafe_operations:
        reasons.extend(analysis.unsafe_operations)
    if any(_unsafe_path(path) for path in analysis.changed_files):
        reasons.append("patch contains a path outside the worktree")

    level = RiskLevel.HIGH if reasons else RiskLevel.LOW
    return PatchRiskDecision(
        level=level,
        requires_approval=level is RiskLevel.HIGH,
        reasons=reasons or ["small patch limited to diagnosed low-risk files"],
        changed_files=analysis.changed_files,
        changed_lines=analysis.changed_lines,
    )


def _unsafe_path(path: str) -> bool:
    candidate = Path(path)
    return candidate.is_absolute() or ".." in candidate.parts
