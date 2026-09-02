from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from repropilot.domain import (
    CommandResult,
    Diagnosis,
    PatchProposal,
    RiskLevel,
    RunRequest,
)


def _orchestrator_contracts():
    try:
        from repropilot.domain import ApprovalDecision, RunStatus
        from repropilot.orchestrator import ReproPilot
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 6 orchestrator is not implemented: {exc}")
    return ApprovalDecision, ReproPilot, RunStatus


def request(
    tmp_path: Path, max_patch_attempts: int = 3, *, formal: bool = False
) -> RunRequest:
    payload: dict[str, Any] = {
            "paper": str(tmp_path / "paper.pdf"),
            "repository": str(tmp_path / "source"),
            "dataset": {"name": "synthetic", "path": str(tmp_path / "data")},
            "command": ["python", "train.py", "--epochs", "1"],
            "limits": {
                "wall_time_seconds": 60,
                "max_patch_attempts": max_patch_attempts,
            },
        }
    if formal:
        payload["formal_experiment"] = {
            "command": ["python", "train.py", "--seed", "{seed}"],
            "seeds": [11, 22, 33],
            "comparison_scope": "paper",
            "scope_evidence": ["paper_spec.json#results[0]"],
        }
    return RunRequest.model_validate(payload)


class FakeServices:
    def __init__(
        self,
        tmp_path: Path,
        *,
        smoke_exit_codes: list[int],
        patch_risk: RiskLevel = RiskLevel.LOW,
        verify_exit_codes: list[int] | None = None,
        smoke_timeouts: list[bool] | None = None,
        formal_exit_codes: list[int] | None = None,
        formal_timeouts: list[bool] | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.smoke_exit_codes = smoke_exit_codes
        self.smoke_timeouts = smoke_timeouts or [False] * len(smoke_exit_codes)
        self.verify_exit_codes = verify_exit_codes or [0, 0, 0]
        self.formal_exit_codes = formal_exit_codes or [0, 0, 0]
        self.formal_timeouts = formal_timeouts or [False, False, False]
        self.patch_risk = patch_risk
        self.proposal_calls = 0
        self.apply_calls: list[PatchProposal] = []
        self.rollback_calls = 0
        self.command_timeouts: list[float] = []
        self.report_statuses: list[str] = []
        self.diagnosed_failures: list[str] = []

    def ingest(self, run_request: RunRequest, store: Any) -> None:
        pass

    def audit(self, run_request: RunRequest, store: Any) -> None:
        pass

    def build(self, run_request: RunRequest, store: Any, timeout: float) -> CommandResult:
        self.command_timeouts.append(timeout)
        return self._result("build", 0)

    def smoke_run(
        self, run_request: RunRequest, store: Any, timeout: float
    ) -> CommandResult:
        self.command_timeouts.append(timeout)
        exit_code = self.smoke_exit_codes.pop(0)
        timed_out = self.smoke_timeouts.pop(0)
        return self._result("smoke", exit_code, timed_out=timed_out)

    def diagnose(self, failed: CommandResult, store: Any) -> Diagnosis:
        self.diagnosed_failures.append(failed.stderr_path.name)
        return Diagnosis(
            category="dependency",
            root_cause="Missing fixture dependency.",
            evidence=["ModuleNotFoundError: fixture"],
            related_files=["requirements.txt"],
            confidence=0.99,
        )

    def formal_experiment(
        self, run_request: RunRequest, store: Any, timeout: float
    ) -> list[CommandResult]:
        results = []
        for index, exit_code in enumerate(self.formal_exit_codes):
            self.command_timeouts.append(timeout)
            results.append(
                self._result(
                    f"formal-{index}",
                    exit_code,
                    timed_out=self.formal_timeouts[index],
                )
            )
        return results

    def propose_patch(self, diagnosis: Diagnosis, store: Any) -> PatchProposal:
        self.proposal_calls += 1
        return PatchProposal(
            diff="""diff --git a/requirements.txt b/requirements.txt
--- a/requirements.txt
+++ b/requirements.txt
@@ -0,0 +1 @@
+fixture==1.0
""",
            explanation="Add the missing fixture dependency.",
            risk=self.patch_risk,
            targeted_test=["pytest", "-q", "tests/test_smoke.py"],
            allowed_paths=["requirements.txt"],
        )

    def apply_patch(self, proposal: PatchProposal, diagnosis: Diagnosis, store: Any) -> None:
        self.apply_calls.append(proposal)

    def verify_patch(
        self, proposal: PatchProposal, store: Any, timeout: float
    ) -> CommandResult:
        self.command_timeouts.append(timeout)
        return self._result("verify", self.verify_exit_codes.pop(0))

    def rollback_patch(self, proposal: PatchProposal, store: Any) -> None:
        self.rollback_calls += 1

    def compare(self, run_request: RunRequest, store: Any) -> None:
        pass

    def score(self, run_request: RunRequest, store: Any) -> None:
        pass

    def report(self, status: str, reason: str | None, store: Any) -> None:
        self.report_statuses.append(status)

    def _result(self, name: str, exit_code: int, *, timed_out: bool = False) -> CommandResult:
        stdout = self.tmp_path / f"{name}-{len(self.command_timeouts)}.stdout.log"
        stderr = self.tmp_path / f"{name}-{len(self.command_timeouts)}.stderr.log"
        stdout.write_text("output", encoding="utf-8")
        stderr.write_text("failure" if exit_code else "", encoding="utf-8")
        return CommandResult(
            exit_code=exit_code,
            stdout_path=stdout,
            stderr_path=stderr,
            duration_seconds=0.1,
            timed_out=timed_out,
        )


def test_successful_smoke_run_follows_the_happy_path(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[0])

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.SUCCEEDED
    assert summary.states == [
        "INGEST",
        "AUDIT",
        "BUILD",
        "SMOKE_RUN",
        "COMPARE",
        "SCORE",
        "REPORT",
    ]


def test_formal_experiment_runs_after_successful_smoke(tmp_path: Path) -> None:
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[0])

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path, formal=True))

    assert summary.status == RunStatus.SUCCEEDED
    assert summary.states == [
        "INGEST",
        "AUDIT",
        "BUILD",
        "SMOKE_RUN",
        "FORMAL_EXPERIMENT",
        "COMPARE",
        "SCORE",
        "REPORT",
    ]


@pytest.mark.parametrize(
    ("exit_codes", "timeouts", "expected_status", "reason"),
    [
        ([0, 1, 0], [False, False, False], "FAILED", "Formal experiment failed for seed 22."),
        (
            [0, 124, 0],
            [False, True, False],
            "TIMED_OUT",
            "Formal experiment timed out for seed 22.",
        ),
    ],
)
def test_formal_experiment_failure_is_terminal_without_repair(
    tmp_path: Path,
    exit_codes: list[int],
    timeouts: list[bool],
    expected_status: str,
    reason: str,
) -> None:
    _, ReproPilot, _ = _orchestrator_contracts()
    services = FakeServices(
        tmp_path,
        smoke_exit_codes=[0],
        formal_exit_codes=exit_codes,
        formal_timeouts=timeouts,
    )

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path, formal=True))

    assert summary.status == expected_status
    assert summary.reason == reason
    assert summary.states[-2:] == ["FORMAL_EXPERIMENT", "REPORT"]
    assert services.proposal_calls == 0


def test_low_risk_failure_is_repaired_then_rerun(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1, 0])

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.SUCCEEDED
    assert summary.attempts == 1
    assert summary.states == [
        "INGEST",
        "AUDIT",
        "BUILD",
        "SMOKE_RUN",
        "DIAGNOSE",
        "APPLY_PATCH",
        "VERIFY",
        "SMOKE_RUN",
        "COMPARE",
        "SCORE",
        "REPORT",
    ]
    assert len(services.apply_calls) == 1


def test_high_risk_patch_pauses_before_mutation(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1], patch_risk=RiskLevel.HIGH)

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.WAITING_APPROVAL
    assert summary.states[-1] == "WAITING_APPROVAL"
    assert services.apply_calls == []
    assert (summary.run_dir / "pending_patch.json").exists()


def test_stops_after_exactly_three_patch_attempts_and_reports(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1, 1, 1, 1])

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.FAILED
    assert summary.attempts == 3
    assert services.proposal_calls == 3
    assert summary.states[-1] == "REPORT"
    assert services.report_statuses == [RunStatus.FAILED]


def test_failed_patch_verification_becomes_the_next_diagnostic_input(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(
        tmp_path,
        smoke_exit_codes=[1, 0],
        verify_exit_codes=[1, 0],
    )

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.SUCCEEDED
    assert summary.attempts == 2
    assert services.diagnosed_failures[0].startswith("smoke-")
    assert services.diagnosed_failures[1].startswith("verify-")


def test_timeout_still_generates_a_terminal_report(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(
        tmp_path,
        smoke_exit_codes=[124],
        smoke_timeouts=[True],
    )

    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.TIMED_OUT
    assert summary.states[-1] == "REPORT"
    assert services.report_statuses == [RunStatus.TIMED_OUT]
    assert all(0 < timeout <= 60 for timeout in services.command_timeouts)


def test_resume_uses_persisted_patch_and_sha_bound_approval(tmp_path: Path):
    ApprovalDecision, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1], patch_risk=RiskLevel.HIGH)
    paused = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))
    pending = json.loads((paused.run_dir / "pending_patch.json").read_text(encoding="utf-8"))
    services.smoke_exit_codes = [0]
    services.smoke_timeouts = [False]
    services.patch_risk = RiskLevel.LOW
    resumed_agent = ReproPilot(tmp_path / "unused", services)

    summary = resumed_agent.resume(
        paused.run_dir,
        ApprovalDecision(
            patch_id=pending["patch_id"],
            patch_sha256=pending["patch_sha256"],
            approved=True,
        ),
    )

    assert summary.status == RunStatus.SUCCEEDED
    assert len(services.apply_calls) == 1
    assert summary.states[-4:] == ["SMOKE_RUN", "COMPARE", "SCORE", "REPORT"]


def test_resume_rejects_approval_for_a_different_patch(tmp_path: Path):
    ApprovalDecision, ReproPilot, _ = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1], patch_risk=RiskLevel.HIGH)
    paused = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))
    pending = json.loads((paused.run_dir / "pending_patch.json").read_text(encoding="utf-8"))

    with pytest.raises(ValueError, match="SHA-256"):
        ReproPilot(tmp_path / "unused", services).resume(
            paused.run_dir,
            ApprovalDecision(
                patch_id=pending["patch_id"],
                patch_sha256="0" * 64,
                approved=True,
            ),
        )
    assert services.apply_calls == []


def test_rejected_patch_goes_directly_to_report(tmp_path: Path):
    ApprovalDecision, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1], patch_risk=RiskLevel.HIGH)
    paused = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))
    pending = json.loads((paused.run_dir / "pending_patch.json").read_text(encoding="utf-8"))

    summary = ReproPilot(tmp_path / "unused", services).resume(
        paused.run_dir,
        ApprovalDecision(
            patch_id=pending["patch_id"],
            patch_sha256=pending["patch_sha256"],
            approved=False,
            reason="Semantic change was not approved.",
        ),
    )

    assert summary.status == RunStatus.REJECTED
    assert summary.states[-1] == "REPORT"
    assert services.apply_calls == []


def test_internal_failure_still_generates_a_terminal_report(tmp_path: Path):
    _, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[0])

    def fail_ingest(run_request: RunRequest, store: Any) -> None:
        raise RuntimeError("fixture ingestion failure")

    services.ingest = fail_ingest  # type: ignore[method-assign]
    summary = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))

    assert summary.status == RunStatus.FAILED
    assert summary.reason == "Internal failure: fixture ingestion failure"
    assert summary.states[-1] == "REPORT"
    assert services.report_statuses == [RunStatus.FAILED]


def test_internal_failure_after_approval_still_generates_report(tmp_path: Path):
    ApprovalDecision, ReproPilot, RunStatus = _orchestrator_contracts()
    services = FakeServices(tmp_path, smoke_exit_codes=[1], patch_risk=RiskLevel.HIGH)
    paused = ReproPilot(tmp_path / "runs", services).run(request(tmp_path))
    pending = json.loads((paused.run_dir / "pending_patch.json").read_text(encoding="utf-8"))

    def fail_apply(proposal: PatchProposal, diagnosis: Diagnosis, store: Any) -> None:
        raise RuntimeError("fixture patch failure")

    services.apply_patch = fail_apply  # type: ignore[method-assign]
    summary = ReproPilot(tmp_path / "unused", services).resume(
        paused.run_dir,
        ApprovalDecision(
            patch_id=pending["patch_id"],
            patch_sha256=pending["patch_sha256"],
            approved=True,
        ),
    )

    assert summary.status == RunStatus.FAILED
    assert summary.reason == "Internal failure: fixture patch failure"
    assert summary.states[-1] == "REPORT"
    assert services.report_statuses == [RunStatus.FAILED]
