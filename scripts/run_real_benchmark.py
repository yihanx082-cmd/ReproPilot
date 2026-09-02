from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import cast

from repropilot.cli import _default_services
from repropilot.real_benchmark import (
    AcquisitionError,
    InjectionError,
    MeasuredPatchGenerator,
    RealBenchmarkCase,
    RealCaseResult,
    acquire_repository,
    aggregate_real_results,
    infrastructure_failure_result,
    load_real_cases,
    render_real_benchmark_html,
    render_real_benchmark_markdown,
    run_agent_case,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run ReproPilot against faults hidden in pinned real repositories"
    )
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path)
    parser.add_argument("--approve-high-risk", action="store_true")
    args = parser.parse_args()

    output = args.output.resolve()
    if output.exists():
        parser.error(f"output already exists: {output}")
    output.mkdir(parents=True)
    source_root = (
        args.source_cache.resolve() if args.source_cache else output / "sources"
    )
    source_root.mkdir(parents=True, exist_ok=True)
    workspace_root = output / "workspaces"
    workspace_root.mkdir()

    root = args.cases.resolve().parent.parent
    cases = load_real_cases(args.cases, root=root)
    services = _default_services()
    patch_generator = cast(MeasuredPatchGenerator, services.patch_generator)
    grouped: dict[str, list[RealBenchmarkCase]] = defaultdict(list)
    for case in cases:
        grouped[case.repository_url].append(case)

    results: list[RealCaseResult] = []
    for repository_cases in grouped.values():
        first = repository_cases[0]
        slug = first.repository_url.removesuffix(".git").rsplit("/", 1)[-1]
        source = source_root / slug
        acquisition_started = time.monotonic()
        try:
            if not source.exists():
                union_paths = sorted(
                    {path for case in repository_cases for path in case.allowed_paths}
                )
                acquisition_case = first.model_copy(
                    update={"allowed_paths": union_paths}
                )
                acquire_repository(acquisition_case, source)
            _validate_cached_source(source, first)
        except (AcquisitionError, OSError, RuntimeError) as exc:
            elapsed = time.monotonic() - acquisition_started
            results.extend(
                infrastructure_failure_result(
                    case,
                    status="acquisition_failed",
                    reason=str(exc),
                    wall_time_seconds=elapsed,
                )
                for case in repository_cases
            )
            continue

        for case in repository_cases:
            workspace = workspace_root / case.id
            shutil.copytree(source, workspace)
            try:
                result = run_agent_case(
                    case,
                    workspace,
                    patch_generator,
                    approve_high_risk=args.approve_high_risk,
                )
            except InjectionError as exc:
                result = infrastructure_failure_result(
                    case,
                    status="injection_failed",
                    reason=str(exc),
                    wall_time_seconds=0,
                )
            results.append(result)
            (output / f"{case.id}.json").write_text(
                result.model_dump_json(indent=2), encoding="utf-8"
            )

    summary = aggregate_real_results(results, mode="real_agent")
    payload = {
        "summary": summary.model_dump(mode="json"),
        "results": [result.model_dump(mode="json") for result in results],
    }
    (output / "benchmark-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / "benchmark-summary.md").write_text(
        render_real_benchmark_markdown(summary, results), encoding="utf-8"
    )
    (output / "benchmark-report.html").write_text(
        render_real_benchmark_html(summary, results), encoding="utf-8"
    )
    print(json.dumps(summary.model_dump(mode="json"), indent=2))
    return 0 if summary.evaluated_case_count and summary.safety_invariants_passed else 1


def _validate_cached_source(source: Path, case: RealBenchmarkCase) -> None:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0 or completed.stdout.strip() != case.commit_sha:
        raise RuntimeError(f"Cached source does not match pinned commit: {source}")
    missing = [path for path in case.allowed_paths if not (source / path).is_file()]
    if missing:
        raise RuntimeError(f"Cached source is missing allowed files: {', '.join(missing)}")


if __name__ == "__main__":
    sys.exit(main())
