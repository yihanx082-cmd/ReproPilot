from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repropilot.benchmark import aggregate_results, load_cases, run_reference_case


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the deterministic ReproPilot benchmark")
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.cases.resolve().parent.parent
    cases = load_cases(args.cases, root=root)
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        result = run_reference_case(case)
        results.append(result)
        (args.output / f"{case.id}.json").write_text(
            result.model_dump_json(indent=2), encoding="utf-8"
        )

    summary = aggregate_results(results, mode="reference_harness_baseline")
    payload = {
        "summary": summary.model_dump(mode="json"),
        "results": [result.model_dump(mode="json") for result in results],
    }
    (args.output / "benchmark-results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "benchmark-summary.md").write_text(
        _markdown_summary(summary.model_dump(mode="json")), encoding="utf-8"
    )

    print(json.dumps(summary.model_dump(mode="json"), indent=2))
    return 0 if summary.safety_invariants_passed else 1


def _markdown_summary(summary: dict[str, object]) -> str:
    return "\n".join(
        [
            "# ReproPilot Benchmark Summary",
            "",
            "> Mode: reference harness baseline. This validates benchmark plumbing; "
            "it is not a claim of model generalization.",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Cases | {summary['case_count']} |",
            f"| Error localization rate | {summary['error_localization_rate']:.1%} |",  # type: ignore[str-format]
            f"| Repair success rate | {summary['repair_success_rate']:.1%} |",  # type: ignore[str-format]
            f"| Post-fix test pass rate | {summary['post_fix_test_pass_rate']:.1%} |",  # type: ignore[str-format]
            f"| Unrelated change rate | {summary['unrelated_change_rate']:.1%} |",  # type: ignore[str-format]
            f"| Mean patch attempts | {summary['mean_patch_attempts']:.2f} |",  # type: ignore[str-format]
            f"| Tool calls | {summary['total_tool_calls']} |",
            f"| Model calls | {summary['total_model_calls']} |",
            f"| Model cost | ${summary['total_model_cost_usd']:.4f} |",  # type: ignore[str-format]
            "",
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
