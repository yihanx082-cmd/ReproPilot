from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from repropilot.artifacts import ArtifactStore
from repropilot.domain import (
    ApprovalDecision,
    CommandResult,
    Diagnosis,
    EventKind,
    EvidenceEvent,
    PatchProposal,
    RiskLevel,
    RunRequest,
    RunState,
    RunStatus,
    RunSummary,
)


class RunServices(Protocol):
    def ingest(self, run_request: RunRequest, store: ArtifactStore) -> None: ...

    def audit(self, run_request: RunRequest, store: ArtifactStore) -> None: ...

    def build(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> CommandResult: ...

    def smoke_run(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> CommandResult: ...

    def formal_experiment(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> list[CommandResult]: ...

    def diagnose(self, failed: CommandResult, store: ArtifactStore) -> Diagnosis: ...

    def propose_patch(self, diagnosis: Diagnosis, store: ArtifactStore) -> PatchProposal: ...

    def apply_patch(
        self, proposal: PatchProposal, diagnosis: Diagnosis, store: ArtifactStore
    ) -> None: ...

    def verify_patch(
        self, proposal: PatchProposal, store: ArtifactStore, timeout: float
    ) -> CommandResult: ...

    def rollback_patch(self, proposal: PatchProposal, store: ArtifactStore) -> None: ...

    def compare(self, run_request: RunRequest, store: ArtifactStore) -> None: ...

    def score(self, run_request: RunRequest, store: ArtifactStore) -> None: ...

    def report(
        self, status: RunStatus, reason: str | None, store: ArtifactStore
    ) -> None: ...


class ReproPilot:
    def __init__(
        self,
        output_root: Path,
        services: RunServices,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.output_root = output_root
        self.services = services
        self.clock = clock

    def run(self, request: RunRequest) -> RunSummary:
        store = ArtifactStore.create(self.output_root, request)
        deadline = self.clock() + request.limits.wall_time_seconds
        store.update_metadata(status=RunStatus.RUNNING.value, attempts=0)
        try:
            self._transition(store, RunState.INGEST, attempts=0)
            self.services.ingest(request, store)
            self._transition(store, RunState.AUDIT, attempts=0)
            self.services.audit(request, store)
            self._transition(store, RunState.BUILD, attempts=0)
            built = self.services.build(request, store, self._remaining(deadline))
            if built.timed_out:
                return self._terminal(
                    store, RunStatus.TIMED_OUT, 0, "Docker build exceeded the run deadline."
                )
            if built.exit_code != 0:
                return self._terminal(store, RunStatus.FAILED, 0, "Docker build failed.")
            self._transition(store, RunState.SMOKE_RUN, attempts=0)
            smoke = self.services.smoke_run(request, store, self._remaining(deadline))
            return self._continue_from_smoke(store, request, smoke, 0, deadline)
        except TimeoutError:
            return self._terminal(store, RunStatus.TIMED_OUT, 0, "Run deadline exhausted.")
        except Exception as exc:
            return self._terminal(store, RunStatus.FAILED, 0, f"Internal failure: {exc}")

    def resume(self, run_dir: Path, approval: ApprovalDecision) -> RunSummary:
        store = ArtifactStore(run_dir)
        metadata = store.read_metadata()
        if metadata.get("status") != RunStatus.WAITING_APPROVAL.value:
            raise ValueError("Run is not waiting for approval")
        pending = store.read_metadata_from("pending_patch.json")
        proposal = PatchProposal.model_validate(pending["proposal"])
        diagnosis = Diagnosis.model_validate(pending["diagnosis"])
        actual_sha256 = hashlib.sha256(proposal.diff.encode()).hexdigest()
        if approval.patch_id != pending["patch_id"]:
            raise ValueError("Approval patch ID does not match the pending patch")
        if actual_sha256 != pending["patch_sha256"] or approval.patch_sha256 != actual_sha256:
            raise ValueError("Approval SHA-256 does not match the pending patch")

        request = RunRequest.model_validate(metadata["request"])
        attempts = int(metadata.get("attempts", 0))
        remaining = float(metadata.get("remaining_seconds", request.limits.wall_time_seconds))
        deadline = self.clock() + remaining
        store.append_event(
            EvidenceEvent(
                kind=EventKind.APPROVAL,
                message="patch_approved" if approval.approved else "patch_rejected",
                data=approval.model_dump(mode="json"),
            )
        )
        if not approval.approved:
            return self._terminal(store, RunStatus.REJECTED, attempts, approval.reason)

        try:
            self._transition(store, RunState.APPLY_PATCH, attempts=attempts)
            self.services.apply_patch(proposal, diagnosis, store)
            self._transition(store, RunState.VERIFY, attempts=attempts)
            verified = self.services.verify_patch(proposal, store, self._remaining(deadline))
            if verified.exit_code != 0 or verified.timed_out:
                self._transition(store, RunState.ROLLBACK, attempts=attempts)
                self.services.rollback_patch(proposal, store)
                status = RunStatus.TIMED_OUT if verified.timed_out else RunStatus.FAILED
                return self._terminal(
                    store, status, attempts, "Approved patch verification failed."
                )
            self._transition(store, RunState.SMOKE_RUN, attempts=attempts)
            smoke = self.services.smoke_run(request, store, self._remaining(deadline))
            return self._continue_from_smoke(store, request, smoke, attempts, deadline)
        except TimeoutError:
            return self._terminal(store, RunStatus.TIMED_OUT, attempts, "Run deadline exhausted.")
        except Exception as exc:
            return self._terminal(
                store, RunStatus.FAILED, attempts, f"Internal failure: {exc}"
            )

    def _continue_from_smoke(
        self,
        store: ArtifactStore,
        request: RunRequest,
        smoke: CommandResult,
        attempts: int,
        deadline: float,
    ) -> RunSummary:
        while True:
            if smoke.timed_out:
                return self._terminal(
                    store, RunStatus.TIMED_OUT, attempts, "Smoke run exceeded the deadline."
                )
            if smoke.exit_code == 0:
                if request.formal_experiment is not None:
                    self._transition(store, RunState.FORMAL_EXPERIMENT, attempts=attempts)
                    formal_results = self.services.formal_experiment(
                        request, store, self._remaining(deadline)
                    )
                    for seed, result in zip(
                        request.formal_experiment.seeds, formal_results, strict=True
                    ):
                        if result.timed_out:
                            return self._terminal(
                                store,
                                RunStatus.TIMED_OUT,
                                attempts,
                                f"Formal experiment timed out for seed {seed}.",
                            )
                        if result.exit_code != 0:
                            return self._terminal(
                                store,
                                RunStatus.FAILED,
                                attempts,
                                f"Formal experiment failed for seed {seed}.",
                            )
                self._transition(store, RunState.COMPARE, attempts=attempts)
                self.services.compare(request, store)
                self._transition(store, RunState.SCORE, attempts=attempts)
                self.services.score(request, store)
                return self._terminal(store, RunStatus.SUCCEEDED, attempts, None)
            if attempts >= request.limits.max_patch_attempts:
                return self._terminal(
                    store,
                    RunStatus.FAILED,
                    attempts,
                    "Maximum patch attempts exhausted.",
                )

            self._transition(store, RunState.DIAGNOSE, attempts=attempts)
            diagnosis = self.services.diagnose(smoke, store)
            proposal = self.services.propose_patch(diagnosis, store)
            attempts += 1
            store.update_metadata(attempts=attempts)
            if proposal.risk is RiskLevel.HIGH:
                return self._pause_for_approval(
                    store, proposal, diagnosis, attempts, self._remaining(deadline)
                )

            self._transition(store, RunState.APPLY_PATCH, attempts=attempts)
            self.services.apply_patch(proposal, diagnosis, store)
            self._transition(store, RunState.VERIFY, attempts=attempts)
            verified = self.services.verify_patch(proposal, store, self._remaining(deadline))
            if verified.exit_code != 0 or verified.timed_out:
                self._transition(store, RunState.ROLLBACK, attempts=attempts)
                self.services.rollback_patch(proposal, store)
                if verified.timed_out:
                    return self._terminal(
                        store, RunStatus.TIMED_OUT, attempts, "Patch verification timed out."
                    )
                smoke = verified
                continue

            self._transition(store, RunState.SMOKE_RUN, attempts=attempts)
            smoke = self.services.smoke_run(request, store, self._remaining(deadline))

    def _pause_for_approval(
        self,
        store: ArtifactStore,
        proposal: PatchProposal,
        diagnosis: Diagnosis,
        attempts: int,
        remaining_seconds: float,
    ) -> RunSummary:
        patch_sha256 = hashlib.sha256(proposal.diff.encode()).hexdigest()
        patch_id = f"patch-{attempts}-{patch_sha256[:8]}"
        store.write_json_artifact(
            "pending_patch.json",
            {
                "patch_id": patch_id,
                "patch_sha256": patch_sha256,
                "proposal": proposal.model_dump(mode="json"),
                "diagnosis": diagnosis.model_dump(mode="json"),
            },
        )
        self._transition(store, RunState.WAITING_APPROVAL, attempts=attempts)
        store.update_metadata(
            status=RunStatus.WAITING_APPROVAL.value,
            attempts=attempts,
            remaining_seconds=remaining_seconds,
            pending_patch_id=patch_id,
        )
        return self._summary(store, RunStatus.WAITING_APPROVAL, attempts, None)

    def _terminal(
        self,
        store: ArtifactStore,
        status: RunStatus,
        attempts: int,
        reason: str | None,
    ) -> RunSummary:
        self._transition(store, RunState.REPORT, attempts=attempts)
        self.services.report(status, reason, store)
        store.update_metadata(
            status=status.value,
            attempts=attempts,
            reason=reason,
        )
        return self._summary(store, status, attempts, reason)

    @staticmethod
    def _transition(store: ArtifactStore, state: RunState, *, attempts: int) -> None:
        store.append_event(
            EvidenceEvent(
                kind=EventKind.STATE,
                message=state.value,
                data={"state": state.value, "attempts": attempts},
            )
        )
        store.update_metadata(current_state=state.value)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self.clock()
        if remaining <= 0:
            raise TimeoutError("Run deadline exhausted")
        return remaining

    @staticmethod
    def _summary(
        store: ArtifactStore,
        status: RunStatus,
        attempts: int,
        reason: str | None,
    ) -> RunSummary:
        states = [
            RunState(event.message)
            for event in store.read_events()
            if event.kind is EventKind.STATE
        ]
        return RunSummary(
            run_dir=store.run_dir,
            status=status,
            states=states,
            attempts=attempts,
            reason=reason,
        )
