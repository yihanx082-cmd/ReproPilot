from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pymupdf
import pytest

from repropilot.artifacts import ArtifactStore
from repropilot.domain import RunRequest


def _paper_contracts():
    try:
        from repropilot.domain import (
            ModelUsage,
            PaperClaim,
            PaperExtraction,
            PaperSpec,
        )
        from repropilot.paper import extract_paper_spec
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 2 paper extraction is not implemented: {exc}")
    return ModelUsage, PaperClaim, PaperExtraction, PaperSpec, extract_paper_spec


class FakeStructuredLLM:
    def __init__(self, extraction: Any) -> None:
        self.extraction = extraction
        self.received_pages: list[Any] = []

    def extract(self, pages: list[Any]) -> Any:
        self.received_pages = pages
        return self.extraction


@pytest.fixture
def tiny_paper(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "tiny-paper.pdf"
    document = pymupdf.open()
    first_page = document.new_page()
    first_page.insert_text(
        (72, 72),
        "Abstract\nA tiny image classification study. Top-1 accuracy is 92.5%.",
    )
    second_page = document.new_page()
    second_page.insert_text(
        (72, 72),
        "Training Details\nWe use Adam with a learning rate of 1e-4 and batch size 64.",
    )
    document.save(pdf_path)
    document.close()
    return pdf_path


def valid_request(tmp_path: Path) -> RunRequest:
    return RunRequest.model_validate(
        {
            "paper": str(tmp_path / "paper.pdf"),
            "repository": "https://github.com/example/project.git",
            "dataset": {"name": "CIFAR-10", "path": str(tmp_path / "data")},
            "command": ["python", "train.py", "--epochs", "1"],
            "environment": {"python": "3.11", "device": "cpu"},
        }
    )


def make_extraction(*claims: Any) -> Any:
    ModelUsage, _, PaperExtraction, PaperSpec, _ = _paper_contracts()
    return PaperExtraction(
        spec=PaperSpec(claims=list(claims)),
        usage=ModelUsage(
            model="fake-model",
            input_tokens=120,
            output_tokens=30,
            duration_seconds=0.25,
            estimated_cost_usd=0.001,
        ),
    )


def test_extracts_claim_with_page_evidence(tiny_paper: Path):
    _, PaperClaim, _, _, extract_paper_spec = _paper_contracts()
    learning_rate = PaperClaim(
        field="optimizer.learning_rate",
        value=1e-4,
        evidence_text="learning rate of 1e-4",
        page=2,
        confidence=0.98,
    )
    llm = FakeStructuredLLM(make_extraction(learning_rate))

    spec = extract_paper_spec(tiny_paper, llm)

    assert spec.claims == [learning_rate]
    assert [page.page for page in llm.received_pages] == [1, 2]
    assert "Training Details" in llm.received_pages[1].text


def test_rejects_claim_when_evidence_is_missing_or_on_the_wrong_page(tiny_paper: Path):
    _, PaperClaim, _, _, extract_paper_spec = _paper_contracts()
    missing = PaperClaim(
        field="augmentation.cutmix_alpha",
        value=1.0,
        evidence_text="CutMix alpha is 1.0",
        page=2,
        confidence=0.91,
    )
    wrong_page = PaperClaim(
        field="optimizer.learning_rate",
        value=1e-4,
        evidence_text="learning rate of 1e-4",
        page=1,
        confidence=0.98,
    )

    spec = extract_paper_spec(
        tiny_paper,
        FakeStructuredLLM(make_extraction(missing, wrong_page)),
    )

    assert spec.claims == []
    assert spec.unresolved_fields == [
        "augmentation.cutmix_alpha",
        "optimizer.learning_rate",
    ]


def test_evidence_matching_ignores_case_and_repeated_whitespace(tiny_paper: Path):
    _, PaperClaim, _, _, extract_paper_spec = _paper_contracts()
    claim = PaperClaim(
        field="training.batch_size",
        value=64,
        evidence_text="ADAM   WITH A LEARNING RATE OF 1E-4",
        page=2,
        confidence=0.95,
    )

    spec = extract_paper_spec(tiny_paper, FakeStructuredLLM(make_extraction(claim)))

    assert spec.claims == [claim]


def test_rejects_claim_outside_reproduction_field_scope(tiny_paper: Path):
    _, PaperClaim, _, _, extract_paper_spec = _paper_contracts()
    unrelated_claim = PaperClaim(
        field="author.description",
        value="image classification study",
        evidence_text="image classification study",
        page=1,
        confidence=0.99,
    )

    spec = extract_paper_spec(
        tiny_paper,
        FakeStructuredLLM(make_extraction(unrelated_claim)),
    )

    assert spec.claims == []
    assert spec.unresolved_fields == ["author.description"]


def test_persists_validated_spec_and_model_usage(tiny_paper: Path, tmp_path: Path):
    _, PaperClaim, _, _, extract_paper_spec = _paper_contracts()
    claim = PaperClaim(
        field="optimizer.learning_rate",
        value=1e-4,
        evidence_text="learning rate of 1e-4",
        page=2,
        confidence=0.98,
    )
    store = ArtifactStore.create(tmp_path / "runs", valid_request(tmp_path))

    extract_paper_spec(tiny_paper, FakeStructuredLLM(make_extraction(claim)), store=store)

    saved = json.loads((store.run_dir / "paper_spec.json").read_text(encoding="utf-8"))
    assert saved["claims"][0]["field"] == "optimizer.learning_rate"
    event = store.read_events()[-1]
    assert event.message == "paper_spec_extracted"
    assert event.data == {
        "accepted_claims": 1,
        "duration_seconds": 0.25,
        "estimated_cost_usd": 0.001,
        "input_tokens": 120,
        "model": "fake-model",
        "output_tokens": 30,
        "rejected_claims": 0,
    }


def test_reported_results_require_page_evidence(tiny_paper: Path):
    ModelUsage, _, PaperExtraction, PaperSpec, extract_paper_spec = _paper_contracts()
    try:
        from repropilot.domain import PaperResult
    except ImportError as exc:
        pytest.fail(f"Task 2 reported-result contract is not implemented: {exc}")

    valid_result = PaperResult(
        metric="top1_accuracy",
        value=92.5,
        unit="percent",
        evidence_text="Top-1 accuracy is 92.5%",
        page=1,
        confidence=0.97,
    )
    wrong_page_result = PaperResult(
        metric="macro_f1",
        value=88.0,
        unit="percent",
        evidence_text="Top-1 accuracy is 92.5%",
        page=2,
        confidence=0.80,
    )
    extraction = PaperExtraction(
        spec=PaperSpec(reported_results=[valid_result, wrong_page_result]),
        usage=ModelUsage(
            model="fake-model",
            input_tokens=120,
            output_tokens=30,
            duration_seconds=0.25,
        ),
    )

    spec = extract_paper_spec(tiny_paper, FakeStructuredLLM(extraction))

    assert spec.reported_results == [valid_result]
    assert spec.unresolved_fields == ["result.macro_f1"]
