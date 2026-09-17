from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
EVIDENCE = ROOT / "benchmark" / "agent-ablation-2026-09-17-summary.json"


def test_published_ablation_evidence_is_real_and_internally_consistent() -> None:
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    assert evidence["fixture_mode"] is False
    assert evidence["git_dirty"] is False
    assert len(evidence["git_commit"]) == 40
    assert len(evidence["manifest_sha256"]) == 64
    assert evidence["repetitions"] == 3
    assert evidence["repositories"] == 3

    raw = evidence["arms"]["single_turn_raw"]
    loop = evidence["arms"]["feedback_loop"]
    memory = evidence["arms"]["episodic_memory"]

    raw_rate = 100 * raw["complete_successes"] / raw["cases"]
    loop_rate = 100 * loop["complete_successes"] / loop["cases"]
    assert loop_rate - raw_rate == evidence["deltas_percentage_points"][
        "feedback_loop_vs_single_turn_raw"
    ]
    assert (raw["passed_stages"], raw["total_stages"]) == (9, 18)
    assert (loop["passed_stages"], loop["total_stages"]) == (18, 18)
    assert all(
        arm["unrelated_changed_lines"] == 0 for arm in evidence["arms"].values()
    )
    assert memory["memory_hits"] == 0


def test_public_copy_preserves_ablation_boundaries() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    resume = (ROOT / "docs" / "product" / "agent-testing-resume-entry.md").read_text(
        encoding="utf-8"
    )
    portfolio = (ROOT / "docs" / "product" / "portfolio-attachment.md").read_text(
        encoding="utf-8"
    )

    for copy in [readme, resume, portfolio]:
        assert "0/9" in copy
        assert "9/9" in copy
        assert "100.0" in copy
        assert "记忆命中" in copy
    assert "通用" in resume
    assert "归因于记忆机制" in portfolio
