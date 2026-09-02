from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from repropilot.domain import (
    CommandResult,
    ModelUsage,
    PaperClaim,
    PaperExtraction,
    PaperResult,
    PaperSpec,
    PatchProposal,
    RiskLevel,
    RunRequest,
    RunStatus,
)
from repropilot.orchestrator import ReproPilot
from repropilot.services import DefaultRunServices


class FakePaperLLM:
    def extract(self, pages: list[Any]) -> PaperExtraction:
        assert "macro-F1 of 0.90" in pages[0].text
        return PaperExtraction(
            spec=PaperSpec(
                claims=[
                    PaperClaim(
                        field="optimizer.learning_rate",
                        value=0.0001,
                        evidence_text="learning rate of 1e-4",
                        page=1,
                        confidence=1,
                    )
                ],
                reported_results=[
                    PaperResult(
                        metric="macro_f1",
                        value=0.90,
                        evidence_text="macro-F1 of 0.90",
                        page=1,
                        confidence=1,
                    )
                ],
            ),
            usage=ModelUsage(
                model="fixture-paper-model",
                input_tokens=20,
                output_tokens=10,
                duration_seconds=0.01,
                estimated_cost_usd=0,
            ),
        )


class FakePatchGenerator:
    def propose(self, diagnosis: Any, worktree: Path, log_tail: str) -> PatchProposal:
        assert diagnosis.category == "dependency"
        assert "ModuleNotFoundError" in log_tail
        return PatchProposal(
            diff="""diff --git a/train.py b/train.py
--- a/train.py
+++ b/train.py
@@ -1,2 +1 @@
-import repropilot_missing_demo_dependency
 print("macro_f1=0.88")
""",
            explanation="Remove the injected unavailable fixture dependency.",
            risk=RiskLevel.LOW,
            targeted_test=["python", "unbounded_model_selected_test.py"],
            allowed_paths=["train.py"],
        )


class LocalFixtureSandbox:
    def __init__(self, worktree: Path, logs_dir: Path) -> None:
        self.worktree = worktree
        self.logs_dir = logs_dir
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    def build(self, context: Path, image_tag: str, timeout: float = 1200) -> CommandResult:
        del context, image_tag, timeout
        return self._result([sys.executable, "-c", "print('build ok')"])

    def run(self, argv: list[str], timeout: float, network: bool = False) -> CommandResult:
        del network
        translated = [sys.executable, *argv[1:]] if argv[0] in {"python", "python3"} else argv
        return self._result(translated, timeout=timeout)

    def _result(self, argv: list[str], timeout: float = 30) -> CommandResult:
        self.count += 1
        started = time.perf_counter()
        completed = subprocess.run(
            argv,
            cwd=self.worktree,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        stdout = self.logs_dir / f"{self.count:03d}.stdout.log"
        stderr = self.logs_dir / f"{self.count:03d}.stderr.log"
        stdout.write_text(completed.stdout, encoding="utf-8")
        stderr.write_text(completed.stderr, encoding="utf-8")
        return CommandResult(
            exit_code=completed.returncode,
            stdout_path=stdout,
            stderr_path=stderr,
            duration_seconds=time.perf_counter() - started,
            argv=argv,
        )


def test_missing_dependency_runs_from_pdf_through_patch_and_html_report(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "train.py").write_text(
        "import repropilot_missing_demo_dependency\nprint(\"macro_f1=0.88\")\n",
        encoding="utf-8",
    )
    (source / "config.yaml").write_text("learning_rate: 0.0001\n", encoding="utf-8")
    original = (source / "train.py").read_bytes()
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "sample.txt").write_text("synthetic", encoding="utf-8")
    paper = tmp_path / "paper.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "We use a learning rate of 1e-4 and report macro-F1 of 0.90.",
    )
    document.save(paper)
    document.close()
    request = RunRequest(
        paper=paper,
        repository=str(source),
        dataset={"name": "synthetic", "path": dataset},
        command=["python", "train.py"],
        limits={"wall_time_seconds": 60, "max_patch_attempts": 3},
    )

    services = DefaultRunServices(
        paper_llm=FakePaperLLM(),
        patch_generator=FakePatchGenerator(),
        sandbox_factory=lambda worktree, source, dataset, logs, image: LocalFixtureSandbox(
            worktree, logs
        ),
    )
    summary = ReproPilot(tmp_path / "runs", services).run(request)

    assert summary.status == RunStatus.SUCCEEDED, summary.reason
    assert summary.attempts == 1
    assert (source / "train.py").read_bytes() == original
    required = {
        "paper_spec.json",
        "repo_facts.json",
        "alignment.json",
        "build.json",
        "diagnosis-1.json",
        "patch-1.json",
        "verify-1.json",
        "evidence_bundle.json",
        "repro_score.json",
        "report.html",
    }
    assert required <= {path.name for path in summary.run_dir.iterdir()}
    evidence = json.loads(
        (summary.run_dir / "evidence_bundle.json").read_text(encoding="utf-8")
    )
    verification = json.loads(
        (summary.run_dir / "verify-1.json").read_text(encoding="utf-8")
    )
    assert verification["argv"][-1] == "train.py"
    assert "unbounded_model_selected_test.py" not in verification["argv"]
    assert evidence["execution_succeeded"] is True
    assert not (summary.run_dir / "worktree" / "train.py").read_text(
        encoding="utf-8"
    ).startswith("import repropilot_missing")
    report = (summary.run_dir / "report.html").read_text(encoding="utf-8")
    assert "PROVISIONAL_SMOKE_RUN" in report
    assert "Remove the injected unavailable fixture dependency" in report
    assert "macro_f1" in report


def test_metric_selection_matches_architecture_and_derives_error_rate() -> None:
    results = [
        PaperResult(
            metric="Error",
            value=8.75,
            unit="%",
            evidence_text="ResNet 20 0.27M 8.75",
            page=7,
            confidence=0.98,
        ),
        PaperResult(
            metric="Error",
            value=7.51,
            unit="%",
            evidence_text="ResNet 32 0.46M 7.51",
            page=7,
            confidence=0.98,
        ),
    ]

    selected = DefaultRunServices._results_for_command(
        results,
        ["python", "trainer.py", "--arch", "resnet20"],
    )
    observed = DefaultRunServices._parse_observed_metrics(" * Prec@1 91.730\n")

    assert selected == [results[0]]
    assert observed["error"] == pytest.approx(8.27)
