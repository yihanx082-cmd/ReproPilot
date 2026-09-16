from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from repropilot.ablation import (
    AblationArm,
    AblationPatchGenerator,
    AblationPatchRequest,
    AblationRunResult,
    ProgressiveCase,
    aggregate_ablation,
    load_ablation_manifest,
    reverse_unified_diff,
    run_ablation_case,
    write_ablation_reports,
)
from repropilot.cli import _default_services
from repropilot.domain import (
    Diagnosis,
    DiagnosisCategory,
    ModelUsage,
    PatchProposal,
    RiskLevel,
)
from repropilot.real_benchmark import RealBenchmarkCase, acquire_repository
from repropilot.repair_memory import SQLiteRepairMemory


class FixturePatchGenerator:
    def __init__(self) -> None:
        self.usage: list[ModelUsage] = []

    def propose(
        self, request: AblationPatchRequest, worktree: Path
    ) -> PatchProposal:
        del worktree
        self.usage.append(
            ModelUsage(
                model="fixture-generator",
                input_tokens=0,
                output_tokens=0,
                duration_seconds=0,
            )
        )
        diff = reverse_unified_diff(
            request.stage.injection.read_text(encoding="utf-8")
        )
        return PatchProposal(
            diff=diff,
            explanation="Fixture generator reverses the frozen injected fault.",
            risk=RiskLevel.LOW,
            targeted_test=["semantic-probe"],
            allowed_paths=[request.stage.probe.path],
        )


class LivePatchGenerator:
    def __init__(self) -> None:
        services = _default_services()
        self._generator = services.patch_generator
        self.usage = cast(list[ModelUsage], self._generator.usage)

    def propose(
        self, request: AblationPatchRequest, worktree: Path
    ) -> PatchProposal:
        diagnosis = request.diagnosis or Diagnosis(
            category=DiagnosisCategory.UNKNOWN,
            root_cause="No structured diagnosis supplied in raw single-turn arm.",
            evidence=[request.stage.probe.failure_message],
            related_files=[request.stage.probe.path],
            confidence=0,
        )
        return self._generator.propose(diagnosis, worktree, request.context)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run progressive ReproPilot Agent ablation experiments"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    parser.add_argument(
        "--arms",
        default=",".join(arm.value for arm in AblationArm),
        help="Comma-separated ablation arms",
    )
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--fixture-mode", type=Path)
    parser.add_argument("--approve-high-risk", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        parser.error(f"output already exists: {output}")
    if args.repetitions < 1:
        parser.error("repetitions must be at least 1")
    try:
        arms = [AblationArm(value.strip()) for value in args.arms.split(",") if value.strip()]
    except ValueError as exc:
        parser.error(str(exc))
    if not arms:
        parser.error("at least one arm is required")

    fixture_mode = args.fixture_mode is not None
    if fixture_mode:
        fixture_path = args.fixture_mode.resolve()
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if fixture.get("schema_version") != 1:
            parser.error("fixture file requires schema_version 1")
        patch_generator: AblationPatchGenerator = FixturePatchGenerator()
    else:
        patch_generator = LivePatchGenerator()

    manifest = args.manifest.resolve()
    root = manifest.parent.parent
    cases = load_ablation_manifest(manifest, root=root)
    if not fixture_mode:
        _require_clean_experiment_tree(root)

    with tempfile.TemporaryDirectory(prefix="repropilot-ablation-") as temp:
        temp_root = Path(temp)
        source_root = (
            args.source_cache.resolve() if args.source_cache else temp_root / "sources"
        )
        source_root.mkdir(parents=True, exist_ok=True)
        sources = {
            case.id: _acquire_case_source(case, source_root)
            for case in cases
        }
        memory = SQLiteRepairMemory(temp_root / "repair-memory.sqlite3")
        runs: list[AblationRunResult] = []
        for arm in arms:
            for repetition in range(1, args.repetitions + 1):
                results = []
                for case in cases:
                    workspace = temp_root / "workspaces" / arm.value / str(repetition) / case.id
                    workspace.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(sources[case.id], workspace)
                    results.append(
                        run_ablation_case(
                            case,
                            workspace,
                            patch_generator,
                            arm=arm,
                            repair_memory=memory,
                            approve_high_risk=args.approve_high_risk,
                        )
                    )
                runs.append(
                    AblationRunResult(
                        arm=arm,
                        repetition=repetition,
                        cases=tuple(results),
                    )
                )

        summary = aggregate_ablation(runs)
        metadata = {
            "git_commit": _git_value(root, ["rev-parse", "HEAD"]),
            "git_dirty": bool(_git_value(root, ["status", "--porcelain"])),
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
            "manifest": str(manifest),
            "repetitions": args.repetitions,
            "arms": [arm.value for arm in arms],
            "model": patch_generator.usage[-1].model if patch_generator.usage else "unknown",
        }
        write_ablation_reports(
            output,
            runs,
            summary,
            fixture_mode=fixture_mode,
            metadata=metadata,
        )

    print(output)
    return 0


def _acquire_case_source(case: ProgressiveCase, source_root: Path) -> Path:
    slug = case.repository_url.removesuffix(".git").rsplit("/", 1)[-1]
    source = source_root / f"{slug}-{case.commit_sha[:8]}"
    if source.exists():
        return source
    first = case.stages[0]
    acquisition_case = RealBenchmarkCase(
        id=case.id,
        repository_url=case.repository_url,
        commit_sha=case.commit_sha,
        license=case.license,
        injection=first.injection,
        expected_category=first.category,
        expected_root_cause=first.root_cause,
        allowed_paths=case.allowed_paths,
        expected_outcome="auto_fix",
        probe=first.probe,
    )
    acquire_repository(acquisition_case, source)
    return source


def _require_clean_experiment_tree(root: Path) -> None:
    changed = _git_value(
        root,
        ["status", "--porcelain", "--", "src", "scripts", "benchmark", "tests"],
    )
    if changed:
        raise RuntimeError(
            "Real-model ablation requires committed evaluator code; dirty paths:\n" + changed
        )


def _git_value(root: Path, argv: list[str]) -> str:
    completed = subprocess.run(
        ["git", *argv],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.stdout.strip() if completed.returncode == 0 else "unknown"


if __name__ == "__main__":
    sys.exit(main())
