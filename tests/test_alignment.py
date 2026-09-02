from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openai import OpenAI

from repropilot.artifacts import ArtifactStore
from repropilot.domain import PaperClaim, PaperSpec


def _alignment_contracts():
    try:
        from repropilot.alignment import align_claims
        from repropilot.domain import RepoFact
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 3 alignment engine is not implemented: {exc}")
    return align_claims, RepoFact


def claim(field: str, value: Any) -> PaperClaim:
    return PaperClaim(
        field=field,
        value=value,
        evidence_text=f"paper evidence for {field}",
        page=3,
        confidence=0.95,
    )


def fact(RepoFact: Any, field: str, value: Any) -> Any:
    return RepoFact(
        field=field,
        value=value,
        source_path="config.yaml",
        line_start=2,
        extractor="yaml",
    )


def test_aligns_matching_mismatching_and_unknown_claims():
    align_claims, RepoFact = _alignment_contracts()
    spec = PaperSpec(
        claims=[
            claim("optimizer.learning_rate", 0.0001),
            claim("training.batch_size", 64),
            claim("training.epochs", 20),
        ]
    )
    facts = [
        fact(RepoFact, "optimizer.learning_rate", 0.001),
        fact(RepoFact, "training.batch_size", 64.0),
    ]

    findings = align_claims(spec, facts)
    by_field = {finding.field: finding for finding in findings}

    assert by_field["optimizer.learning_rate"].status == "mismatch"
    assert by_field["optimizer.learning_rate"].severity == "warning"
    assert by_field["training.batch_size"].status == "match"
    assert by_field["training.epochs"].status == "unknown"
    assert by_field["training.epochs"].repo_fact is None


@pytest.mark.parametrize(
    ("field", "paper_value", "repository_value"),
    [
        ("dataset.split_strategy", "patient_level", "image_random"),
        ("metrics.f1_average", "macro", "micro"),
    ],
)
def test_marks_data_and_metric_mismatches_as_critical(
    field: str,
    paper_value: str,
    repository_value: str,
):
    align_claims, RepoFact = _alignment_contracts()

    finding = align_claims(
        PaperSpec(claims=[claim(field, paper_value)]),
        [fact(RepoFact, field, repository_value)],
    )[0]

    assert finding.status == "mismatch"
    assert finding.severity == "critical"
    assert finding.paper_claim.page == 3
    assert finding.repo_fact.source_path == "config.yaml"


def test_reports_missing_readme_script_as_repository_only_mismatch():
    align_claims, RepoFact = _alignment_contracts()
    missing_script = RepoFact(
        field="readme.missing_script",
        value="removed_train.py",
        source_path="README.md",
        line_start=6,
        extractor="readme",
    )

    finding = align_claims(PaperSpec(), [missing_script])[0]

    assert finding.field == "readme.missing_script"
    assert finding.status == "mismatch"
    assert finding.severity == "warning"
    assert finding.paper_claim is None


def test_marks_pretrained_weight_version_mismatch_as_warning():
    align_claims, RepoFact = _alignment_contracts()

    finding = align_claims(
        PaperSpec(claims=[claim("model.pretrained_weights", "resnet50-v2")]),
        [fact(RepoFact, "model.pretrained_weights", "resnet50-v1")],
    )[0]

    assert finding.status == "mismatch"
    assert finding.severity == "warning"


def test_uses_semantic_matcher_only_when_exact_field_mapping_is_unresolved():
    align_claims, RepoFact = _alignment_contracts()
    learning_rate = fact(RepoFact, "optimizer.base_lr", 0.0001)
    batch_size = fact(RepoFact, "training.batch_size", 64)

    class FakeSemanticMatcher:
        def __init__(self) -> None:
            self.fields: list[str] = []

        def match(self, paper_claim: PaperClaim, candidates: list[Any]) -> Any:
            self.fields.append(paper_claim.field)
            return learning_rate

    matcher = FakeSemanticMatcher()
    findings = align_claims(
        PaperSpec(
            claims=[
                claim("optimizer.learning_rate", 0.0001),
                claim("training.batch_size", 64),
            ]
        ),
        [learning_rate, batch_size],
        semantic_matcher=matcher,
    )

    assert matcher.fields == ["optimizer.learning_rate"]
    assert findings[0].status == "match"
    assert findings[0].paper_claim.page == 3
    assert findings[0].repo_fact.source_path == "config.yaml"


def test_persists_alignment_findings_deterministically(tmp_path: Any):
    align_claims, RepoFact = _alignment_contracts()
    store = ArtifactStore(tmp_path / "run")
    store.run_dir.mkdir()
    spec = PaperSpec(claims=[claim("training.batch_size", 64)])
    facts = [fact(RepoFact, "training.batch_size", 64)]

    first = align_claims(spec, facts, store=store)
    first_content = (store.run_dir / "alignment.json").read_text(encoding="utf-8")
    second = align_claims(spec, facts, store=store)

    assert first == second
    assert (store.run_dir / "alignment.json").read_text(encoding="utf-8") == first_content


def test_rejects_semantic_fact_that_was_not_scanned():
    align_claims, RepoFact = _alignment_contracts()
    scanned = fact(RepoFact, "optimizer.base_lr", 0.0001)
    fabricated = RepoFact(
        field="optimizer.base_lr",
        value=0.0001,
        source_path="invented.yaml",
        line_start=999,
        extractor="yaml",
    )

    class FabricatingMatcher:
        def match(self, paper_claim: PaperClaim, candidates: list[Any]) -> Any:
            return fabricated

    with pytest.raises(ValueError, match="scanned repository facts"):
        align_claims(
            PaperSpec(claims=[claim("optimizer.learning_rate", 0.0001)]),
            [scanned],
            semantic_matcher=FabricatingMatcher(),
        )


def test_openai_semantic_matcher_selects_a_cited_scanner_candidate():
    try:
        from repropilot.alignment import OpenAICompatibleSemanticMatcher
    except ImportError as exc:
        pytest.fail(f"OpenAI-compatible semantic matcher is not implemented: {exc}")
    _, RepoFact = _alignment_contracts()
    captured_requests: list[dict[str, Any]] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1_700_000_000,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(
                                {
                                    "candidate_index": 0,
                                    "explanation": "base_lr denotes learning rate",
                                }
                            ),
                        },
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    candidate = fact(RepoFact, "optimizer.base_lr", 0.0001)

    selected = OpenAICompatibleSemanticMatcher(client, "test-model").match(
        claim("optimizer.learning_rate", 0.0001), [candidate]
    )

    assert selected is candidate
    request_text = captured_requests[0]["messages"][1]["content"]
    assert '"page": 3' in request_text
    assert '"source_path": "config.yaml"' in request_text
    assert captured_requests[0]["response_format"]["type"] == "json_schema"
