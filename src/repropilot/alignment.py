from __future__ import annotations

import json
import re
from typing import Any, Protocol

from openai import OpenAI
from pydantic import BaseModel, Field

from repropilot.artifacts import ArtifactStore
from repropilot.domain import (
    AlignmentFinding,
    FindingSeverity,
    FindingStatus,
    PaperClaim,
    PaperSpec,
    RepoFact,
)

CRITICAL_FIELDS = {"dataset.split_strategy", "metrics.f1_average"}
SEMANTIC_ALIGNMENT_PROMPT = """\
Map a paper claim to one repository fact only when both fields clearly describe
the same reproduction setting. Return the zero-based candidate_index, or null
when uncertain. Never invent a candidate, file path, line number, or value.
"""


class SemanticMatchSelection(BaseModel):
    candidate_index: int | None = Field(default=None, ge=0)
    explanation: str = Field(min_length=1)


class SemanticMatcherResponseError(RuntimeError):
    """Raised when a semantic matcher returns no usable structured response."""


class SemanticFieldMatcher(Protocol):
    def match(self, paper_claim: PaperClaim, candidates: list[RepoFact]) -> RepoFact | None: ...


class OpenAICompatibleSemanticMatcher:
    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def match(self, paper_claim: PaperClaim, candidates: list[RepoFact]) -> RepoFact | None:
        if not candidates:
            return None
        payload = {
            "paper_claim": paper_claim.model_dump(mode="json"),
            "repository_candidates": [
                {"candidate_index": index, **fact.model_dump(mode="json")}
                for index, fact in enumerate(candidates)
            ],
        }
        completion = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": SEMANTIC_ALIGNMENT_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format=SemanticMatchSelection,
        )
        selection = completion.choices[0].message.parsed
        if selection is None:
            raise SemanticMatcherResponseError("Model returned no semantic match selection")
        if selection.candidate_index is None:
            return None
        if selection.candidate_index >= len(candidates):
            raise SemanticMatcherResponseError("Model selected an out-of-range candidate")
        return candidates[selection.candidate_index]


def align_claims(
    spec: PaperSpec,
    facts: list[RepoFact],
    *,
    semantic_matcher: SemanticFieldMatcher | None = None,
    store: ArtifactStore | None = None,
) -> list[AlignmentFinding]:
    facts_by_field: dict[str, list[RepoFact]] = {}
    for fact in facts:
        facts_by_field.setdefault(fact.field, []).append(fact)

    findings: list[AlignmentFinding] = []
    semantic_candidates = [fact for fact in facts if fact.field != "readme.missing_script"]
    for claim in spec.claims:
        candidates = facts_by_field.get(claim.field, [])
        if not candidates and semantic_matcher is not None:
            semantic_fact = semantic_matcher.match(claim, semantic_candidates)
            if semantic_fact is not None and semantic_fact not in semantic_candidates:
                raise ValueError("Semantic matcher must select from scanned repository facts")
            candidates = [semantic_fact] if semantic_fact is not None else []
        findings.append(_align_claim(claim, candidates))
    findings.extend(
        AlignmentFinding(
            field=fact.field,
            repo_fact=fact,
            status=FindingStatus.MISMATCH,
            severity=FindingSeverity.WARNING,
            explanation=f"README references missing script {fact.value!r}.",
        )
        for fact in facts_by_field.get("readme.missing_script", [])
    )
    if store is not None:
        store.write_json_artifact(
            "alignment.json",
            [finding.model_dump(mode="json") for finding in findings],
        )
    return findings


def _align_claim(claim: PaperClaim, candidates: list[RepoFact]) -> AlignmentFinding:
    if not candidates:
        return AlignmentFinding(
            field=claim.field,
            paper_claim=claim,
            status=FindingStatus.UNKNOWN,
            severity=FindingSeverity.WARNING,
            explanation="The paper states this value, but no repository evidence was found.",
        )

    fact = candidates[0]
    if _normalized(claim.value) == _normalized(fact.value):
        return AlignmentFinding(
            field=claim.field,
            paper_claim=claim,
            repo_fact=fact,
            status=FindingStatus.MATCH,
            severity=FindingSeverity.INFO,
            explanation="Paper and repository values match.",
        )

    severity = (
        FindingSeverity.CRITICAL
        if claim.field in CRITICAL_FIELDS
        else FindingSeverity.WARNING
    )
    return AlignmentFinding(
        field=claim.field,
        paper_claim=claim,
        repo_fact=fact,
        status=FindingStatus.MISMATCH,
        severity=severity,
        explanation=(
            f"Paper value {claim.value!r} differs from repository value {fact.value!r}."
        ),
    )


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"[\s-]+", "_", value.strip().lower())
    return value
