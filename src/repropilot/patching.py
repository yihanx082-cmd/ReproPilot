from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Protocol

from repropilot.domain import CommandResult, Diagnosis, PatchProposal
from repropilot.policy import PatchAnalysis, analyze_patch


class PatchValidationError(ValueError):
    """Raised when a proposed diff violates the patch safety contract."""


class PatchApplyError(RuntimeError):
    """Raised when Git cannot validate, apply, or reverse a patch."""


class TargetedVerifier(Protocol):
    def run(self, argv: list[str]) -> CommandResult: ...


class PatchTransaction:
    def __init__(
        self,
        root: Path,
        proposal: PatchProposal,
        diagnosis: Diagnosis,
        verifier: TargetedVerifier,
    ) -> None:
        self.root = root.resolve()
        self.proposal = proposal
        self.diagnosis = diagnosis
        self.verifier = verifier
        self.analysis: PatchAnalysis | None = None
        self.pre_patch_hash: str | None = None
        self.pre_patch_diff: str | None = None
        self.applied = False

    def validate(self) -> PatchAnalysis:
        if not self.proposal.diff.startswith("diff --git "):
            raise PatchValidationError("Patch must be a unified Git diff")
        analysis = analyze_patch(self.proposal.diff)
        if not analysis.changed_files:
            raise PatchValidationError("Patch contains no changed files")
        if analysis.unsafe_operations:
            operations = ", ".join(analysis.unsafe_operations)
            raise PatchValidationError(f"Unsupported patch operation: {operations}")

        allowed = set(self.proposal.allowed_paths)
        diagnosed = set(self.diagnosis.related_files)
        for path in analysis.changed_files:
            candidate = Path(path)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise PatchValidationError("Patch path escapes the cloned worktree")
            if path not in allowed:
                raise PatchValidationError(f"Patch path {path!r} is outside allowed_paths")
            if path not in diagnosed:
                raise PatchValidationError(f"Patch path {path!r} is outside diagnosed files")
            resolved = (self.root / candidate).resolve()
            if not resolved.is_relative_to(self.root):
                raise PatchValidationError("Patch path escapes the cloned worktree")

        self.analysis = analysis
        return analysis

    def apply(self) -> None:
        self.validate()
        self.pre_patch_hash = workspace_hash(self.root)
        self.pre_patch_diff = self._git(["diff", "--binary"]).stdout
        checked = self._git(
            ["apply", "--check", "--whitespace=nowarn", "-"],
            input_text=self.proposal.diff,
        )
        if checked.returncode != 0:
            raise PatchApplyError(f"git apply --check failed: {checked.stderr.strip()}")
        applied = self._git(
            ["apply", "--whitespace=nowarn", "-"],
            input_text=self.proposal.diff,
        )
        if applied.returncode != 0:
            raise PatchApplyError(f"git apply failed: {applied.stderr.strip()}")
        self.applied = True

    def verify(self) -> CommandResult:
        if not self.applied:
            raise PatchApplyError("Patch must be applied before verification")
        result = self.verifier.run(self.proposal.targeted_test)
        if result.exit_code != 0 or result.timed_out:
            self.rollback()
        return result

    def rollback(self) -> None:
        if not self.applied:
            return
        reversed_patch = self._git(
            ["apply", "--reverse", "--whitespace=nowarn", "-"],
            input_text=self.proposal.diff,
        )
        if reversed_patch.returncode != 0:
            raise PatchApplyError(f"git apply --reverse failed: {reversed_patch.stderr.strip()}")
        self.applied = False
        if self.pre_patch_hash is None or workspace_hash(self.root) != self.pre_patch_hash:
            raise PatchApplyError("Rollback did not restore the exact pre-patch workspace")

    def _git(
        self, args: list[str], *, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            input=input_text,
            capture_output=True,
            check=False,
            shell=False,
            text=True,
        )


def workspace_hash(root: Path) -> str:
    digest = hashlib.sha256()
    root = root.resolve()
    files = sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(root).parts
    )
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()
