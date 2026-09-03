from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol, TypeVar

from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
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
    FormalExperimentEvidence,
    ModelUsage,
    PaperResult,
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
from repropilot.repository import execution_request_facts, scan_repository
from repropilot.sandbox import DockerSandbox
from repropilot.scoring import (
    compare_metric,
    result_proximity_evidence,
    score_reproduction,
)

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


class PatchEdit(BaseModel):
    path: str = Field(min_length=1)
    search: str = Field(min_length=1)
    replacement: str


class PatchEditDraft(BaseModel):
    edits: list[PatchEdit] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    targeted_test: list[str] = Field(min_length=1)


class OpenAICompatiblePatchGenerator:
    def __init__(
        self,
        client: OpenAI,
        model: str,
        *,
        structured_output_mode: str = "json_schema",
    ) -> None:
        self.client = client
        self.model = model
        self.structured_output_mode = structured_output_mode
        self.usage: list[ModelUsage] = []

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
        patch_instruction = (
            "Generate minimal exact search-and-replace edits for the diagnosed failure. "
            "Each search string must match exactly once in the supplied file and include "
            "enough unchanged context to be unique. Fix all occurrences needed to resolve "
            "the same root cause. targeted_test must contain one command argument per JSON "
            "array element, for example [\"python\", \"trainer.py\", \"--help\"]. "
            if self.structured_output_mode == "json_object"
            else (
                "Generate one minimal, complete unified Git diff for the diagnosed "
                "failure. The diff must begin with 'diff --git a/... b/...', contain "
                "exact hunk counts, and contain no Markdown fences. "
            )
        )
        if diagnosis.category.value == "cuda_runtime":
            patch_instruction += (
                "A CUDA-to-CPU repair is incomplete unless it updates every unconditional "
                "device transfer, adds torch.load map_location when checkpoint loading is "
                "present, and safely handles optional checkpoint metadata such as epoch "
                "when loading pretrained weights. Include all applicable changes now. "
            )
        messages: list[ChatCompletionMessageParam] = [
            {
                "role": "system",
                "content": (
                    patch_instruction
                    + "Touch only diagnosis.related_files, include one explicit argv test, "
                    "and do not add downloads, shell commands, or unrelated refactors."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        if self.structured_output_mode == "json_object":
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Return valid JSON matching this JSON schema: "
                        + json.dumps(PatchEditDraft.model_json_schema())
                    ),
                }
            )
            return self._propose_from_edits(messages, files, worktree, diagnosis)

        draft: PatchDraft | None = None
        validation_error = ""
        for attempt in range(2):
            draft = self._request_draft(messages)
            validation_error = self._git_apply_error(draft.diff, worktree)
            if not validation_error:
                break
            if attempt == 0:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The diff failed git apply --check. Return corrected JSON with "
                            "a complete unified Git diff beginning with "
                            "'diff --git a/... b/...', no Markdown fences, and exact hunk "
                            f"counts. Error: {validation_error[:2000]}"
                        ),
                    }
                )
        if draft is None or validation_error:
            raise RuntimeError(
                "Patch failed git apply --check after one correction: "
                + validation_error
            )
        provisional = PatchProposal(
            **draft.model_dump(),
            risk=RiskLevel.HIGH,
        )
        decision = assess_patch(provisional.diff, diagnosis)
        return provisional.model_copy(update={"risk": decision.level})

    def _propose_from_edits(
        self,
        messages: list[ChatCompletionMessageParam],
        files: dict[str, str],
        worktree: Path,
        diagnosis: Diagnosis,
    ) -> PatchProposal:
        error = ""
        draft: PatchDraft | None = None
        for attempt in range(2):
            edit_draft = self._request_edit_draft(messages)
            try:
                draft = self._render_edit_draft(edit_draft, files)
                error = self._git_apply_error(draft.diff, worktree)
                if not error:
                    break
            except RuntimeError as exc:
                error = str(exc)
            if attempt == 0:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The edits could not be applied exactly. Return corrected JSON "
                            "using exact, unique text copied from the supplied files. "
                            f"Error: {error[:2000]}"
                        ),
                    }
                )
        if draft is None or error:
            raise RuntimeError("Patch edits remained invalid after one correction: " + error)
        provisional = PatchProposal(**draft.model_dump(), risk=RiskLevel.HIGH)
        decision = assess_patch(provisional.diff, diagnosis)
        return provisional.model_copy(update={"risk": decision.level})

    def _request_edit_draft(
        self, messages: list[ChatCompletionMessageParam]
    ) -> PatchEditDraft:
        response_format: ResponseFormatJSONObject = {"type": "json_object"}
        started = time.monotonic()
        completion = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            response_format=response_format,
            extra_body={"thinking": {"type": "disabled"}},
            max_tokens=4096,
        )
        self._record_usage(completion, started)
        content = completion.choices[0].message.content
        if not content:
            raise RuntimeError("Patch model returned no structured edits")
        return PatchEditDraft.model_validate_json(content)

    @staticmethod
    def _render_edit_draft(
        draft: PatchEditDraft, files: dict[str, str]
    ) -> PatchDraft:
        updated = dict(files)
        changed_paths: list[str] = []
        for edit in draft.edits:
            if edit.path not in updated:
                raise RuntimeError(f"Edit path is not an allowed related file: {edit.path}")
            matches = updated[edit.path].count(edit.search)
            if matches != 1:
                raise RuntimeError(
                    f"Search text in {edit.path} matched {matches} times instead of once"
                )
            updated[edit.path] = updated[edit.path].replace(
                edit.search, edit.replacement, 1
            )
            if edit.path not in changed_paths:
                changed_paths.append(edit.path)

        chunks: list[str] = []
        for path in changed_paths:
            if updated[path] == files[path]:
                continue
            body = "".join(
                difflib.unified_diff(
                    files[path].splitlines(keepends=True),
                    updated[path].splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            chunks.append(f"diff --git a/{path} b/{path}\n{body}")
        if not chunks:
            raise RuntimeError("Edits produced no file changes")
        targeted_test = draft.targeted_test
        if len(targeted_test) == 1:
            targeted_test = shlex.split(targeted_test[0])
        return PatchDraft(
            diff="".join(chunks),
            explanation=draft.explanation,
            targeted_test=targeted_test,
            allowed_paths=changed_paths,
        )

    def _request_draft(
        self, messages: list[ChatCompletionMessageParam]
    ) -> PatchDraft:
        started = time.monotonic()
        completion = self.client.chat.completions.parse(
            model=self.model,
            messages=messages,
            response_format=PatchDraft,
        )
        self._record_usage(completion, started)
        draft = completion.choices[0].message.parsed
        if draft is None:
            raise RuntimeError("Patch model returned no structured patch")
        return draft

    def _record_usage(self, completion: Any, started: float) -> None:
        usage = getattr(completion, "usage", None)
        self.usage.append(
            ModelUsage(
                model=str(getattr(completion, "model", self.model)),
                input_tokens=int(getattr(usage, "prompt_tokens", 0)),
                output_tokens=int(getattr(usage, "completion_tokens", 0)),
                duration_seconds=time.monotonic() - started,
                estimated_cost_usd=None,
            )
        )

    @staticmethod
    def _git_apply_error(diff: str, worktree: Path) -> str:
        if not diff.startswith("diff --git a/"):
            return "diff does not start with a complete 'diff --git' header"
        completed = subprocess.run(
            ["git", "apply", "--check", "--whitespace=nowarn", "-"],
            cwd=worktree,
            input=diff,
            capture_output=True,
            text=True,
            check=False,
        )
        return completed.stderr.strip() if completed.returncode else ""


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
        extract_paper_spec(
            run_request.paper,
            self.paper_llm,
            store=store,
            focus={
                "dataset": run_request.dataset.name,
                "command": run_request.command,
            },
        )

    def audit(self, run_request: RunRequest, store: ArtifactStore) -> None:
        spec = PaperSpec.model_validate(store.read_metadata_from("paper_spec.json"))
        facts = [
            *scan_repository(self._worktree(store)),
            *execution_request_facts(run_request),
        ]
        facts = sorted(facts, key=lambda fact: (fact.source_path, fact.line_start, fact.field))
        store.write_json_artifact(
            "repo_facts.json", [fact.model_dump(mode="json") for fact in facts]
        )
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

    def formal_experiment(
        self, run_request: RunRequest, store: ArtifactStore, timeout: float
    ) -> list[CommandResult]:
        experiment = run_request.formal_experiment
        if experiment is None:
            return []

        deadline = time.monotonic() + timeout
        results: list[CommandResult] = []
        manifest_results: list[dict[str, object]] = []
        for seed in experiment.seeds:
            command = [token.replace("{seed}", str(seed)) for token in experiment.command]
            result = self._sandbox(store, run_request).run(
                command, max(0.001, deadline - time.monotonic())
            )
            artifact = f"formal-seed-{seed}.json"
            self._record_command(store, artifact, "formal_experiment", result)
            results.append(result)
            manifest_results.append(
                {
                    "seed": seed,
                    "artifact": artifact,
                    "argv": result.argv,
                    "exit_code": result.exit_code,
                    "timed_out": result.timed_out,
                    "duration_seconds": result.duration_seconds,
                    "image_digest": result.image_digest,
                    "dockerfile_sha256": result.dockerfile_sha256,
                }
            )
        store.write_json_artifact(
            "experiment_manifest.json",
            {
                "seeds": experiment.seeds,
                "comparison_scope": experiment.comparison_scope,
                "scope_evidence": experiment.scope_evidence,
                "results": manifest_results,
            },
        )
        return results

    def diagnose(self, failed: CommandResult, store: ArtifactStore) -> Diagnosis:
        log_tail = self._command_log(failed)
        worktree = self._worktree(store)
        related = self._implicated_files(log_tail, worktree)
        diagnosis = diagnose_failure(failed.argv, log_tail, related)
        attempt = int(store.read_metadata().get("attempts", 0)) + 1
        store.write_json_artifact(
            f"diagnosis-{attempt}.json", diagnosis.model_dump(mode="json")
        )
        store.write_json_artifact(
            f"failure-{attempt}.json", failed.model_dump(mode="json")
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
        attempt = int(store.read_metadata().get("attempts", 0)) + 1
        failed = CommandResult.model_validate(
            store.read_metadata_from(f"failure-{attempt}.json")
        )
        log_tail = self._command_log(failed)
        worktree = self._worktree(store)
        prior_diffs: list[str] = []
        if attempt > 1:
            prior_diffs = [
                PatchProposal.model_validate(
                    store.read_metadata_from(f"patch-{attempt - 1}.json")
                ).diff
            ]
            with self._temporary_patched_worktree(worktree, prior_diffs) as patched:
                proposal = self.patch_generator.propose(diagnosis, patched, log_tail)
        else:
            proposal = self.patch_generator.propose(diagnosis, worktree, log_tail)
        proposal = proposal.model_copy(update={"targeted_test": failed.argv})
        if prior_diffs:
            cumulative = self._combine_diffs(worktree, [*prior_diffs, proposal.diff])
            proposal = proposal.model_copy(update={"diff": cumulative})
        decision = assess_patch(proposal.diff, diagnosis)
        proposal = proposal.model_copy(
            update={
                "allowed_paths": decision.changed_files,
                "risk": decision.level,
            }
        )
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
        spec = PaperSpec.model_validate(store.read_metadata_from("paper_spec.json"))
        successful_runs = self._successful_formal_results(store)
        selection_command = run_request.command
        if not successful_runs:
            successful_runs = [self._latest_successful_smoke(store)]
        elif run_request.formal_experiment is not None:
            selection_command = run_request.formal_experiment.command
        observed_runs = [
            self._parse_observed_metrics(
                result.stdout_path.read_text(encoding="utf-8", errors="replace")
            )
            for result in successful_runs
        ]
        comparisons = []
        for result in self._results_for_command(
            spec.reported_results, selection_command
        ):
            key = self._metric_key(result.metric)
            if all(key in observed for observed in observed_runs):
                comparisons.append(
                    compare_metric(
                        result.metric,
                        paper_value=result.value,
                        run_values=[observed[key] for observed in observed_runs],
                        evidence=[
                            *(run.stdout_path.name for run in successful_runs),
                            "paper_spec.json",
                        ],
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
        formal = self._formal_experiment_evidence(store)
        formal_success = (
            formal is not None
            and len({result.seed for result in formal.results}) >= 3
            and all(result.exit_code == 0 and not result.timed_out for result in formal.results)
        )
        paper_scope = formal is not None and formal.comparison_scope == "paper"
        dataset_matched = any(
            finding.field.startswith("dataset.") and finding.status.value == "match"
            for finding in findings
        )
        result_evidence = ["experiment_manifest.json", "metric_comparisons.json"]
        proximity = result_proximity_evidence(
            comparisons,
            comparable=paper_scope and formal_success,
            evidence=result_evidence,
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
                status=EvidenceStatus.VERIFIED
                if data_available and dataset_matched
                else EvidenceStatus.PARTIAL
                if data_available
                else EvidenceStatus.UNKNOWN,
                evidence=["alignment.json", "experiment_manifest.json"]
                if data_available and dataset_matched and formal is not None
                else ["run.json"]
                if data_available
                else [],
            ),
            configuration=DimensionEvidence(
                status=configuration_status,
                evidence=["alignment.json"] if findings else [],
            ),
            metrics=DimensionEvidence(
                status=EvidenceStatus.VERIFIED if comparisons else EvidenceStatus.UNKNOWN,
                evidence=["metric_comparisons.json"] if comparisons else [],
            ),
            random_seeds=DimensionEvidence(
                status=EvidenceStatus.VERIFIED
                if formal_success
                else EvidenceStatus.FAILED
                if formal is not None
                else EvidenceStatus.UNKNOWN,
                evidence=[
                    "experiment_manifest.json",
                    *(result.artifact for result in formal.results),
                ]
                if formal is not None
                else [],
            ),
            result_proximity=proximity,
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
            dataset_subset=not paper_scope,
            status=None,
            paper_source=str(request.paper),
            repository_source=request.repository,
            dataset_source=f"{request.dataset.name}: {request.dataset.path}",
            alignment_findings=findings,
            model_usage=self._model_usage(store),
            formal_experiment=formal,
            unresolved_risks=[
                (
                    "Paper-comparison scope relies on declared citations preserved in "
                    "experiment_manifest.json."
                    if paper_scope
                    else "Smoke-run dataset or epoch scope differs from a full paper reproduction."
                )
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

    @staticmethod
    def _combine_diffs(worktree: Path, diffs: list[str]) -> str:
        with DefaultRunServices._temporary_patched_worktree(worktree, diffs) as patched:
            combined = subprocess.run(
                ["git", "diff", "--binary", "--no-color"],
                cwd=patched,
                capture_output=True,
                text=True,
                check=False,
            )
            if combined.returncode != 0 or not combined.stdout:
                raise RuntimeError(
                    "Cannot render cumulative patch: " + combined.stderr.strip()
                )
            return combined.stdout

    @staticmethod
    @contextmanager
    def _temporary_patched_worktree(
        worktree: Path, diffs: list[str]
    ) -> Iterator[Path]:
        with tempfile.TemporaryDirectory(prefix="repropilot-combine-") as temp_dir:
            temporary_worktree = Path(temp_dir) / "worktree"
            created = subprocess.run(
                ["git", "worktree", "add", "--detach", str(temporary_worktree), "HEAD"],
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode != 0:
                raise RuntimeError(
                    "Cannot create temporary Git worktree: " + created.stderr.strip()
                )
            try:
                for diff in diffs:
                    applied = subprocess.run(
                        ["git", "apply", "--whitespace=nowarn", "-"],
                        cwd=temporary_worktree,
                        input=diff,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    if applied.returncode != 0:
                        raise RuntimeError(
                            "Cannot combine repair patches: " + applied.stderr.strip()
                        )
                yield temporary_worktree
            finally:
                subprocess.run(
                    ["git", "worktree", "remove", "--force", str(temporary_worktree)],
                    cwd=worktree,
                    capture_output=True,
                    text=True,
                    check=False,
                )

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
    def _formal_experiment_evidence(
        store: ArtifactStore,
    ) -> FormalExperimentEvidence | None:
        path = store.run_dir / "experiment_manifest.json"
        if not path.exists():
            return None
        return FormalExperimentEvidence.model_validate_json(path.read_text(encoding="utf-8"))

    @classmethod
    def _successful_formal_results(cls, store: ArtifactStore) -> list[CommandResult]:
        evidence = cls._formal_experiment_evidence(store)
        if evidence is None:
            return []
        results = [
            CommandResult.model_validate_json(
                (store.run_dir / item.artifact).read_text(encoding="utf-8")
            )
            for item in evidence.results
        ]
        if any(result.exit_code != 0 or result.timed_out for result in results):
            return []
        return results

    @staticmethod
    def _metric_key(value: str) -> str:
        key = re.sub(r"[^a-z0-9]", "", value.casefold())
        return {
            "classificationerror": "error",
            "testerror": "error",
        }.get(key, key)

    @classmethod
    def _parse_observed_metrics(cls, text: str) -> dict[str, float]:
        observed = {
            cls._metric_key(match.group(1)): float(match.group(2))
            for match in re.finditer(
                r"([A-Za-z][\w-]*)\s*[=:]\s*([0-9]*\.?[0-9]+)", text
            )
        }
        for match in re.finditer(
            r"\b(Prec@1|Acc@1|Top-1 accuracy)\s*[=:]?\s*([0-9]*\.?[0-9]+)",
            text,
            flags=re.IGNORECASE,
        ):
            observed[cls._metric_key(match.group(1))] = float(match.group(2))
        return cls._derived_metrics(observed)

    @staticmethod
    def _derived_metrics(observed: dict[str, float]) -> dict[str, float]:
        derived = dict(observed)
        for accuracy_key in ("prec1", "acc1", "top1accuracy"):
            if accuracy_key in observed:
                derived.setdefault("error", 100.0 - observed[accuracy_key])
                break
        return derived

    @classmethod
    def _results_for_command(
        cls, results: list[PaperResult], argv: list[str]
    ) -> list[PaperResult]:
        architecture = ""
        if "--arch" in argv:
            index = argv.index("--arch")
            if index + 1 < len(argv):
                architecture = cls._metric_key(argv[index + 1])

        counts: dict[str, int] = {}
        for result in results:
            key = cls._metric_key(result.metric)
            counts[key] = counts.get(key, 0) + 1
        return [
            result
            for result in results
            if counts[cls._metric_key(result.metric)] == 1
            or (
                architecture
                and architecture in cls._metric_key(result.evidence_text)
            )
        ]

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
            or path.name.startswith("formal-seed-")
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
