from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Protocol, TypeVar

from openai import OpenAI
from pydantic import BaseModel, Field

from repropilot.alignment import align_claims
from repropilot.artifacts import ArtifactStore
from repropilot.diagnosis import diagnose_failure
from repropilot.domain import (
    AlignmentFinding,
    ApprovalDecision,
    CommandResult,
    Diagnosis,
    DimensionEvidence,
    EventKind,
    EvidenceBundle,
    EvidenceEvent,
    EvidenceStatus,
    ModelUsage,
    PaperSpec,
    PatchProposal,
    RepairAttempt,
    RiskLevel,
    RunRequest,
    RunStatus,
)
from repropilot.paper import StructuredLLM, extract_paper_spec
from repropilot.patching import PatchTransaction, workspace_hash
from repropilot.policy import assess_patch
from repropilot.reporting import render_report
from repropilot.repository import scan_repository
from repropilot.sandbox import DockerSandbox
from repropilot.scoring import compare_metric, score_reproduction

ModelT = TypeVar("ModelT", bound=BaseModel)


class PatchGenerator(Protocol):
    def propose(
        self, diagnosis: Diagnosis, worktree: Path, log_tail: str
    ) -> PatchProposal: ...


class Sandbox(Protocol):
    def build(
        self, context: Path, image_tag: str, timeout: float = 1200
    ) -> CommandResult: ...

    def run(
        self, argv: list[str], timeout: float, network: bool = False
    ) -> CommandResult: ...


class SandboxFactory(Protocol):
    def __call__(
        self,
        worktree: Path,
        source: Path,
        dataset: Path,
        logs: Path,
        image: str,
    ) -> Sandbox: ...


class PatchDraft(BaseModel):
    diff: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    targeted_test: list[str] = Field(min_length=1)
    allowed_paths: list[str] = Field(min_length=1)


class OpenAICompatiblePatchGenerator:
    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def propose(
        self, diagnosis: Diagnosis, worktree: Path, log_tail: str
    ) -> PatchProposal:
        files: dict[str, str] = {}
        for relative in diagnosis.related_files[:3]:
            candidate = (worktree / relative).resolve()
            if candidate.is_relative_to(worktree.resolve()) and candidate.is_file():
                files[relative] = candidate.read_text(encoding="utf-8", errors="replace")[:20000]
        payload = {
            "diagnosis": diagnosis.model_dump(mode="json"),
            "log_tail": log_tail[-12000:],
            "files": files,
        }
        completion = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate one minimal unified Git diff for the diagnosed failure. "
                        "Touch only diagnosis.related_files, include one explicit argv test, "
                        "and do not add downloads, shell commands, or unrelated refactors."
                    ),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format=PatchDraft,
        )
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("Patch model returned no structured patch")
        provisional = PatchProposal(
            **draft.model_dump(),
            risk=RiskLevel.HIGH,
        )
        decision = assess_patch(provisional.diff, diagnosis)
        return provisional.model_copy(update={"risk": decision.level})


class DefaultRunServices:
    def __init__(
        self,
        *,
        paper_llm: StructuredLLM,
        patch_generator: PatchGenerator,
        sandbox_factory: SandboxFactory | None = None,
        docker_executable: str | None = None,
    ) -> None:
        self.paper_llm = paper_llm
        self.patch_generator = patch_generator
        self.docker_executable = docker_executable or os.environ.get(
            "REPROPILOT_DOCKER_BIN", "docker"
        )
        self.sandbox_factory = sandbox_factory or self._docker_sandbox
        self._sandboxes: dict[Path, Sandbox] = {}

    def ingest(self, run_request: RunRequest, store: ArtifactStore) -> None:
        if not run_request.paper.is_file():
            raise FileNotFoundError(f"Paper PDF does not exist: {run_request.paper}")
        if not run_request.dataset.path.is_dir():
            raise FileNotFoundError(
                f"Dataset directory does not exist: {run_request.dataset.path}"
            )

        source = self._materialize_source(run_request.repository, store.run_dir)
        worktree = store.run_dir / "worktree"
        shutil.copytree(source, worktree)
        self._ensure_git_repository(worktree)
        context = self._write_docker_context(worktree, run_request, store.run_dir)
        image = f"repropilot-{store.run_dir.name.lower()}"
        store.update_metadata(
            source_path=str(source),
            worktree_path=str(worktree),
            docker_context=str(context),
            image_tag=image,
        )
        extract_paper_spec(run_request.paper, self.paper_llm, store=store)

    def audit(self, run_request: RunRequest, store: ArtifactStore) -> None:
        del run_request
        spec = PaperSpec.model_validate(store.read_metadata_from("paper_spec.json"))
        facts = scan_repository(self._worktree(store), store=store)
        align_claims(spec, facts, store=store)

    def build(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> CommandResult:
        metadata = store.read_metadata()
        result = self._sandbox(store, run_request).build(
            Path(metadata["docker_context"]), str(metadata["image_tag"]), timeout
        )
        self._record_command(store, "build.json", "docker_build", result)
        return result

    def smoke_run(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> CommandResult:
        result = self._sandbox(store, run_request).run(run_request.command, timeout)
        attempt = int(store.read_metadata().get("attempts", 0))
        self._record_command(store, f"smoke-{attempt}.json", "smoke_run", result)
        return result

    def diagnose(self, failed: CommandResult, store: ArtifactStore) -> Diagnosis:
        log_tail = self._command_log(failed)
        worktree = self._worktree(store)
        related = self._implicated_files(log_tail, worktree)
        diagnosis = diagnose_failure(failed.argv, log_tail, related)
        attempt = int(store.read_metadata().get("attempts", 0)) + 1
        store.write_json_artifact(
            f"diagnosis-{attempt}.json", diagnosis.model_dump(mode="json")
        )
        store.append_event(
            EvidenceEvent(
                kind=EventKind.DIAGNOSIS,
                message="failure_diagnosed",
                data={"attempt": attempt, **diagnosis.model_dump(mode="json")},
            )
        )
        return diagnosis

    def propose_patch(self, diagnosis: Diagnosis, store: ArtifactStore) -> PatchProposal:
        failed = self._latest_command(store, "smoke-")
        log_tail = self._command_log(failed)
        proposal = self.patch_generator.propose(diagnosis, self._worktree(store), log_tail)
        decision = assess_patch(proposal.diff, diagnosis)
        proposal = proposal.model_copy(update={"risk": decision.level})
        attempt = int(store.read_metadata().get("attempts", 0)) + 1
        store.write_json_artifact(
            f"patch-{attempt}.json", proposal.model_dump(mode="json")
        )
        store.append_event(
            EvidenceEvent(
                kind=EventKind.PATCH,
                message="patch_proposed",
                data={
                    "attempt": attempt,
                    "risk": proposal.risk.value,
                    "changed_files": decision.changed_files,
                    "changed_lines": decision.changed_lines,
                },
            )
        )
        return proposal

    def apply_patch(
        self, proposal: PatchProposal, diagnosis: Diagnosis, store: ArtifactStore
    ) -> None:
        transaction = PatchTransaction(
            self._worktree(store), proposal, diagnosis, _UnusedVerifier()
        )
        transaction.apply()
        attempt = int(store.read_metadata().get("attempts", 0))
        store.write_json_artifact(
            f"patch-state-{attempt}.json",
            {
                "pre_patch_hash": transaction.pre_patch_hash,
                "patch_sha256": hashlib.sha256(proposal.diff.encode()).hexdigest(),
            },
        )

    def verify_patch(
        self, proposal: PatchProposal, store: ArtifactStore, timeout: float
    ) -> CommandResult:
        request = RunRequest.model_validate(store.read_metadata()["request"])
        result = self._sandbox(store, request).run(proposal.targeted_test, timeout)
        attempt = int(store.read_metadata().get("attempts", 0))
        self._record_command(store, f"verify-{attempt}.json", "patch_test", result)
        return result

    def rollback_patch(self, proposal: PatchProposal, store: ArtifactStore) -> None:
        worktree = self._worktree(store)
        completed = subprocess.run(
            ["git", "apply", "--reverse", "--whitespace=nowarn", "-"],
            cwd=worktree,
            input=proposal.diff,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Patch rollback failed: {completed.stderr.strip()}")
        attempt = int(store.read_metadata().get("attempts", 0))
        state = store.read_metadata_from(f"patch-state-{attempt}.json")
        if workspace_hash(worktree) != state["pre_patch_hash"]:
            raise RuntimeError("Patch rollback did not restore the exact workspace")

    def compare(self, run_request: RunRequest, store: ArtifactStore) -> None:
        del run_request
        spec = PaperSpec.model_validate(store.read_metadata_from("paper_spec.json"))
        successful = self._latest_successful_smoke(store)
        text = successful.stdout_path.read_text(encoding="utf-8", errors="replace")
        observed = {
            self._metric_key(match.group(1)): float(match.group(2))
            for match in re.finditer(r"([A-Za-z][\w-]*)\s*[=:]\s*([0-9]*\.?[0-9]+)", text)
        }
        comparisons = []
        artifact = successful.stdout_path.name
        for result in spec.reported_results:
            key = self._metric_key(result.metric)
            if key in observed:
                comparisons.append(
                    compare_metric(
                        result.metric,
                        paper_value=result.value,
                        run_values=[observed[key]],
                        evidence=[artifact, "paper_spec.json"],
                    )
                )
        store.write_json_artifact(
            "metric_comparisons.json",
            [comparison.model_dump(mode="json") for comparison in comparisons],
        )

    def score(self, run_request: RunRequest, store: ArtifactStore) -> None:
        bundle = self._build_evidence_bundle(run_request, store)
        store.write_json_artifact("evidence_bundle.json", bundle.model_dump(mode="json"))
        score = score_reproduction(bundle)
        store.write_json_artifact("repro_score.json", score.model_dump(mode="json"))

    def report(
        self, status: RunStatus, reason: str | None, store: ArtifactStore
    ) -> None:
        metadata = store.read_metadata()
        request = RunRequest.model_validate(metadata["request"])
        bundle_path = store.run_dir / "evidence_bundle.json"
        if bundle_path.exists():
            bundle = EvidenceBundle.model_validate_json(
                bundle_path.read_text(encoding="utf-8")
            )
        else:
            bundle = self._build_evidence_bundle(request, store)
        bundle = bundle.model_copy(
            update={
                "status": status,
                "terminal_reason": reason,
                "execution_succeeded": status is RunStatus.SUCCEEDED,
                "commands": self._all_commands(store),
                "repair_attempts": self._repair_attempts(store),
                "duration_seconds": self._total_command_duration(store),
            }
        )
        store.write_json_artifact("evidence_bundle.json", bundle.model_dump(mode="json"))
        store.write_json_artifact(
            "repro_score.json", score_reproduction(bundle).model_dump(mode="json")
        )
        render_report(bundle, store.run_dir / "report.html")

    def _build_evidence_bundle(
        self, request: RunRequest, store: ArtifactStore
    ) -> EvidenceBundle:
        findings = self._read_models(store, "alignment.json", AlignmentFinding)
        comparisons_path = store.run_dir / "metric_comparisons.json"
        comparisons = []
        if comparisons_path.exists():
            from repropilot.domain import MetricComparison

            comparisons = self._read_models(store, "metric_comparisons.json", MetricComparison)
        build_path = store.run_dir / "build.json"
        build_result = (
            CommandResult.model_validate_json(build_path.read_text(encoding="utf-8"))
            if build_path.exists()
            else None
        )
        build_succeeded = build_result is not None and build_result.exit_code == 0
        data_available = request.dataset.path.is_dir()
        configuration_status = EvidenceStatus.UNKNOWN
        if findings:
            configuration_status = (
                EvidenceStatus.VERIFIED
                if all(finding.status.value == "match" for finding in findings)
                else EvidenceStatus.PARTIAL
            )
        return EvidenceBundle(
            environment=DimensionEvidence(
                status=EvidenceStatus.VERIFIED
                if build_succeeded
                else EvidenceStatus.FAILED
                if build_result is not None
                else EvidenceStatus.UNKNOWN,
                evidence=["build.json"] if build_result is not None else [],
            ),
            data=DimensionEvidence(
                status=EvidenceStatus.PARTIAL
                if data_available
                else EvidenceStatus.UNKNOWN,
                evidence=["run.json"] if data_available else [],
            ),
            configuration=DimensionEvidence(
                status=configuration_status,
                evidence=["alignment.json"] if findings else [],
            ),
            metrics=DimensionEvidence(
                status=EvidenceStatus.VERIFIED if comparisons else EvidenceStatus.UNKNOWN,
                evidence=["metric_comparisons.json"] if comparisons else [],
            ),
            random_seeds=DimensionEvidence(status=EvidenceStatus.UNKNOWN),
            result_proximity=DimensionEvidence(
                status=EvidenceStatus.VERIFIED if comparisons else EvidenceStatus.UNKNOWN,
                evidence=["metric_comparisons.json"] if comparisons else [],
            ),
            external_dependencies=DimensionEvidence(
                status=EvidenceStatus.VERIFIED
                if build_succeeded
                else EvidenceStatus.FAILED
                if build_result is not None
                else EvidenceStatus.UNKNOWN,
                evidence=["build.json"] if build_result is not None else [],
            ),
            metric_comparisons=comparisons,
            execution_succeeded=True,
            evidence_complete=(store.run_dir / "paper_spec.json").exists(),
            dataset_subset=True,
            status=None,
            paper_source=str(request.paper),
            repository_source=request.repository,
            dataset_source=f"{request.dataset.name}: {request.dataset.path}",
            alignment_findings=findings,
            model_usage=self._model_usage(store),
            unresolved_risks=[
                "Smoke-run dataset or epoch scope differs from a full paper reproduction."
            ],
        )

    def _sandbox(self, store: ArtifactStore, request: RunRequest) -> Sandbox:
        key = store.run_dir.resolve()
        if key not in self._sandboxes:
            metadata = store.read_metadata()
            self._sandboxes[key] = self.sandbox_factory(
                Path(metadata["worktree_path"]),
                Path(metadata["source_path"]),
                request.dataset.path,
                store.run_dir / "logs",
                str(metadata["image_tag"]),
            )
        return self._sandboxes[key]

    def _docker_sandbox(
        self,
        worktree: Path,
        source: Path,
        dataset: Path,
        logs: Path,
        image: str,
    ) -> DockerSandbox:
        return DockerSandbox(
            worktree=worktree,
            source=source,
            dataset=dataset,
            logs_dir=logs,
            image_tag=image,
            docker_executable=self.docker_executable,
            secrets=[os.environ.get("OPENAI_API_KEY", "")],
        )

    @staticmethod
    def _materialize_source(repository: str, run_dir: Path) -> Path:
        local = Path(repository).expanduser()
        if local.is_dir():
            return local.resolve()
        source = run_dir / "source"
        completed = subprocess.run(
            ["git", "clone", "--depth", "1", repository, str(source)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"Repository clone failed: {completed.stderr.strip()}")
        return source

    @staticmethod
    def _ensure_git_repository(worktree: Path) -> None:
        if (worktree / ".git").exists():
            return
        commands = [
            ["git", "init"],
            ["git", "add", "."],
            [
                "git",
                "-c",
                "user.name=ReproPilot",
                "-c",
                "user.email=repropilot@localhost",
                "commit",
                "-m",
                "baseline",
            ],
        ]
        for command in commands:
            completed = subprocess.run(
                command, cwd=worktree, capture_output=True, text=True, check=False
            )
            if completed.returncode != 0:
                raise RuntimeError(f"Cannot initialize worktree: {completed.stderr.strip()}")

    @staticmethod
    def _write_docker_context(
        worktree: Path, request: RunRequest, run_dir: Path
    ) -> Path:
        context = run_dir / "docker-context"
        context.mkdir()
        lines = [
            f"FROM python:{request.environment.python}-slim",
            "WORKDIR /workspace",
        ]
        requirements = worktree / "requirements.txt"
        if requirements.is_file():
            shutil.copy2(requirements, context / "requirements.txt")
            lines.extend(
                [
                    "COPY requirements.txt /tmp/requirements.txt",
                    "RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt",
                ]
            )
        (context / "Dockerfile").write_text("\n".join(lines) + "\n", encoding="utf-8")
        return context

    @staticmethod
    def _worktree(store: ArtifactStore) -> Path:
        return Path(store.read_metadata()["worktree_path"])

    @staticmethod
    def _record_command(
        store: ArtifactStore, filename: str, message: str, result: CommandResult
    ) -> None:
        store.write_json_artifact(filename, result.model_dump(mode="json"))
        store.append_event(
            EvidenceEvent(
                kind=EventKind.COMMAND,
                message=message,
                data={"artifact": filename, **result.model_dump(mode="json")},
            )
        )

    @staticmethod
    def _command_log(result: CommandResult) -> str:
        return "\n".join(
            [
                result.stdout_path.read_text(encoding="utf-8", errors="replace"),
                result.stderr_path.read_text(encoding="utf-8", errors="replace"),
            ]
        )[-20000:]

    @staticmethod
    def _implicated_files(log: str, worktree: Path) -> list[str]:
        related: list[str] = []
        for raw in re.findall(r'File "([^"]+)"', log):
            candidate = Path(raw)
            if candidate.is_absolute():
                try:
                    relative = candidate.resolve().relative_to(worktree.resolve()).as_posix()
                except ValueError:
                    relative = candidate.name
            else:
                relative = candidate.as_posix().removeprefix("/workspace/")
            if (worktree / relative).is_file() and relative not in related:
                related.append(relative)
        return related

    @staticmethod
    def _latest_command(store: ArtifactStore, prefix: str) -> CommandResult:
        paths = sorted(store.run_dir.glob(f"{prefix}*.json"))
        if not paths:
            raise RuntimeError(f"No {prefix} command artifact exists")
        return CommandResult.model_validate_json(paths[-1].read_text(encoding="utf-8"))

    def _latest_successful_smoke(self, store: ArtifactStore) -> CommandResult:
        results = [
            CommandResult.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted(store.run_dir.glob("smoke-*.json"))
        ]
        successful = [result for result in results if result.exit_code == 0]
        if not successful:
            raise RuntimeError("No successful smoke result is available")
        return successful[-1]

    @staticmethod
    def _metric_key(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.casefold())

    @staticmethod
    def _read_models(
        store: ArtifactStore, filename: str, model: type[ModelT]
    ) -> list[ModelT]:
        path = store.run_dir / filename
        if not path.exists():
            return []
        values = json.loads(path.read_text(encoding="utf-8"))
        return [model.model_validate(value) for value in values]

    @staticmethod
    def _all_commands(store: ArtifactStore) -> list[list[str]]:
        return [
            CommandResult.model_validate_json(path.read_text(encoding="utf-8")).argv
            for path in sorted(store.run_dir.glob("*.json"))
            if path.name == "build.json"
            or path.name.startswith("smoke-")
            or path.name.startswith("verify-")
        ]

    @staticmethod
    def _repair_attempts(store: ArtifactStore) -> list[RepairAttempt]:
        attempts: list[RepairAttempt] = []
        for diagnosis_path in sorted(store.run_dir.glob("diagnosis-*.json")):
            index = diagnosis_path.stem.split("-")[-1]
            patch_path = store.run_dir / f"patch-{index}.json"
            verify_path = store.run_dir / f"verify-{index}.json"
            approval_path = store.run_dir / "approval.json"
            attempts.append(
                RepairAttempt(
                    diagnosis=Diagnosis.model_validate_json(
                        diagnosis_path.read_text(encoding="utf-8")
                    ),
                    patch=PatchProposal.model_validate_json(
                        patch_path.read_text(encoding="utf-8")
                    )
                    if patch_path.exists()
                    else None,
                    approval=ApprovalDecision.model_validate_json(
                        approval_path.read_text(encoding="utf-8")
                    )
                    if approval_path.exists()
                    else None,
                    test_result=CommandResult.model_validate_json(
                        verify_path.read_text(encoding="utf-8")
                    )
                    if verify_path.exists()
                    else None,
                )
            )
        return attempts

    @staticmethod
    def _total_command_duration(store: ArtifactStore) -> float:
        total = 0.0
        for event in store.read_events():
            duration = event.data.get("duration_seconds")
            if event.kind is EventKind.COMMAND and isinstance(duration, int | float):
                total += float(duration)
        return total

    @staticmethod
    def _model_usage(store: ArtifactStore) -> list[ModelUsage]:
        usages: list[ModelUsage] = []
        for event in store.read_events():
            if event.message != "paper_spec_extracted":
                continue
            usages.append(
                ModelUsage(
                    model=str(event.data.get("model", "unknown")),
                    input_tokens=int(event.data.get("input_tokens", 0)),
                    output_tokens=int(event.data.get("output_tokens", 0)),
                    duration_seconds=float(event.data.get("duration_seconds", 0)),
                    estimated_cost_usd=event.data.get("estimated_cost_usd"),
                )
            )
        return usages


class _UnusedVerifier:
    def run(self, argv: list[str]) -> CommandResult:
        del argv
        raise RuntimeError("Verification is executed by DefaultRunServices.verify_patch")
