from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

ALLOWED_EXECUTABLES = {"python", "python3", "pytest"}
SHELL_OPERATORS = {"&", "&&", "|", "||", ";", ">", ">>", "<"}
BLOCKED_OPTIONS = {"--privileged"}


class RiskDecision(BaseModel):
    allowed: bool
    reason: str = Field(min_length=1)


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
