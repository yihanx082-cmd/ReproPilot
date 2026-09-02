from __future__ import annotations

from pathlib import Path

from repropilot.domain import (
    AlignmentFinding,
    ApprovalDecision,
    CommandResult,
    Diagnosis,
    DimensionEvidence,
    EvidenceBundle,
    EvidenceStatus,
    MetricComparison,
    ModelUsage,
    PatchProposal,
    RepairAttempt,
    RiskLevel,
    RunStatus,
)
from repropilot.reporting import render_report


def _evidence(status: EvidenceStatus, artifact: str = "") -> DimensionEvidence:
    return DimensionEvidence(status=status, evidence=[artifact] if artifact else [])


def _bundle(tmp_path: Path, **overrides: object) -> EvidenceBundle:
    stdout = tmp_path / "stdout.log"
    stderr = tmp_path / "stderr.log"
    stdout.write_text("1 passed", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    values: dict[str, object] = {
        "environment": _evidence(EvidenceStatus.VERIFIED, "environment.json"),
        "data": _evidence(EvidenceStatus.PARTIAL, "data.json"),
        "configuration": _evidence(EvidenceStatus.VERIFIED, "alignment.json"),
        "metrics": _evidence(EvidenceStatus.VERIFIED, "metrics.json"),
        "random_seeds": _evidence(EvidenceStatus.UNKNOWN),
        "result_proximity": _evidence(EvidenceStatus.VERIFIED, "comparison.json"),
        "external_dependencies": _evidence(EvidenceStatus.VERIFIED, "dependencies.json"),
        "metric_comparisons": [
            MetricComparison(
                name="macro-F1",
                paper_value=0.91,
                run_values=[0.89, 0.90, 0.90],
                delta=-0.013333,
                mean=0.896667,
                std=0.004714,
                comparable=True,
                evidence=["metrics.json"],
            )
        ],
        "status": RunStatus.SUCCEEDED,
        "paper_source": "paper.pdf#page=5",
        "repository_source": "https://github.com/example/repo@abc123",
        "dataset_source": "CIFAR-10 subset",
        "alignment_findings": [
            AlignmentFinding(
                field="learning_rate",
                status="mismatch",
                severity="warning",
                explanation="Paper says 1e-4; config says 1e-3 <script>alert(1)</script>",
            )
        ],
        "commands": [["python", "train.py", "--epochs", "1"]],
        "repair_attempts": [
            RepairAttempt(
                diagnosis=Diagnosis(
                    category="dependency",
                    root_cause="Missing torchvision",
                    evidence=["ModuleNotFoundError: torchvision"],
                    confidence=0.99,
                ),
                patch=PatchProposal(
                    diff="diff --git a/requirements.txt b/requirements.txt\n+torchvision\n",
                    explanation="Add the missing dependency.",
                    risk=RiskLevel.LOW,
                    targeted_test=["pytest", "-q"],
                    allowed_paths=["requirements.txt"],
                ),
                approval=ApprovalDecision(
                    patch_id="patch-1",
                    patch_sha256="a" * 64,
                    approved=True,
                ),
                test_result=CommandResult(
                    exit_code=0,
                    stdout_path=stdout,
                    stderr_path=stderr,
                    duration_seconds=1.25,
                ),
            )
        ],
        "duration_seconds": 42.5,
        "model_usage": [
            ModelUsage(
                model="gpt-test",
                input_tokens=100,
                output_tokens=20,
                duration_seconds=0.5,
                estimated_cost_usd=0.0123,
            )
        ],
        "unresolved_risks": ["Pretrained weight version is unknown."],
    }
    values.update(overrides)
    return EvidenceBundle.model_validate(values)


def test_report_contains_the_complete_evidence_chain_and_escapes_html(tmp_path: Path) -> None:
    output = render_report(_bundle(tmp_path), tmp_path / "report.html")
    html = output.read_text(encoding="utf-8")

    assert "SUCCEEDED" in html
    assert "80.0 / 100" in html
    assert "learning_rate" in html
    assert "python train.py --epochs 1" in html
    assert "Missing torchvision" in html
    assert "+torchvision" in html
    assert "approved" in html
    assert "exit code 0" in html
    assert "macro-F1" in html
    assert "42.50 seconds" in html
    assert "$0.0123" in html
    assert "Pretrained weight version is unknown." in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert "<script" not in html.lower()
    assert "https://cdn" not in html


def test_smoke_run_report_has_an_explicit_non_reproduction_warning(tmp_path: Path) -> None:
    html = render_report(
        _bundle(tmp_path, dataset_subset=True), tmp_path / "smoke.html"
    ).read_text(encoding="utf-8")

    assert "PROVISIONAL_SMOKE_RUN" in html
    assert "not a full paper reproduction" in html
    assert "not comparable" in html


def test_missing_sections_show_unknown_and_terminal_reason(tmp_path: Path) -> None:
    bundle = _bundle(
        tmp_path,
        status=RunStatus.TIMED_OUT,
        terminal_reason="Docker build exceeded the run deadline.",
        alignment_findings=[],
        commands=[],
        repair_attempts=[],
        metric_comparisons=[],
        model_usage=[],
        duration_seconds=None,
    )

    html = render_report(bundle, tmp_path / "timeout.html").read_text(encoding="utf-8")

    assert "TIMED_OUT" in html
    assert "Docker build exceeded the run deadline." in html
    assert html.count("unknown") >= 4


def test_report_render_is_deterministic(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    first = render_report(bundle, tmp_path / "first.html").read_text(encoding="utf-8")
    second = render_report(bundle, tmp_path / "second.html").read_text(encoding="utf-8")

    assert first == second
