from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Protocol

import pymupdf
from openai import OpenAI

from repropilot.artifacts import ArtifactStore
from repropilot.domain import (
    EventKind,
    EvidenceEvent,
    ModelUsage,
    PaperClaim,
    PaperExtraction,
    PaperPage,
    PaperResult,
    PaperSpec,
)

PAPER_EXTRACTION_PROMPT = """\
Extract reproduction facts from the provided machine-learning paper pages.

Return only claims about: model name/version, dataset, split strategy,
preprocessing, augmentation, optimizer, learning rate, batch size, epochs,
seed policy, pretrained weights, metrics, and reported metric values.

Every claim and reported result must include an exact evidence_text quote and
the one-based page number containing that quote. Put fields that cannot be
supported by exact page evidence in unresolved_fields. Do not infer missing
values and do not treat related wording as an exact quote.
"""

REPRODUCTION_FIELD_ROOTS = frozenset(
    {
        "augmentation",
        "dataset",
        "metrics",
        "model",
        "optimizer",
        "preprocessing",
        "training",
    }
)


class PaperModelResponseError(RuntimeError):
    """Raised when a model response contains no parsed paper specification."""


class OpenAICompatiblePaperLLM:
    def __init__(self, client: OpenAI, model: str) -> None:
        self.client = client
        self.model = model

    def extract(self, pages: list[PaperPage]) -> PaperExtraction:
        page_text = "\n\n".join(f"[PAGE {page.page}]\n{page.text}" for page in pages)
        started_at = time.perf_counter()
        completion = self.client.chat.completions.parse(
            model=self.model,
            messages=[
                {"role": "system", "content": PAPER_EXTRACTION_PROMPT},
                {"role": "user", "content": page_text},
            ],
            response_format=PaperSpec,
        )
        duration_seconds = time.perf_counter() - started_at
        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise PaperModelResponseError("Model returned no parsed paper specification")

        usage = completion.usage
        return PaperExtraction(
            spec=parsed,
            usage=ModelUsage(
                model=completion.model,
                input_tokens=usage.prompt_tokens if usage is not None else 0,
                output_tokens=usage.completion_tokens if usage is not None else 0,
                duration_seconds=duration_seconds,
            ),
        )


class StructuredLLM(Protocol):
    def extract(self, pages: list[PaperPage]) -> PaperExtraction: ...


def extract_paper_spec(
    pdf_path: Path,
    llm: StructuredLLM,
    *,
    store: ArtifactStore | None = None,
) -> PaperSpec:
    pages = _read_pdf_pages(pdf_path)
    extraction = llm.extract(pages)
    validated_spec = _validate_claim_evidence(extraction.spec, pages)

    if store is not None:
        store.write_json_artifact(
            "paper_spec.json",
            validated_spec.model_dump(mode="json"),
        )
        store.append_event(
            EvidenceEvent(
                kind=EventKind.RESULT,
                message="paper_spec_extracted",
                data={
                    "accepted_claims": len(validated_spec.claims),
                    "duration_seconds": extraction.usage.duration_seconds,
                    "estimated_cost_usd": extraction.usage.estimated_cost_usd,
                    "input_tokens": extraction.usage.input_tokens,
                    "model": extraction.usage.model,
                    "output_tokens": extraction.usage.output_tokens,
                    "rejected_claims": len(extraction.spec.claims) - len(validated_spec.claims),
                },
            )
        )

    return validated_spec


def _read_pdf_pages(pdf_path: Path) -> list[PaperPage]:
    with pymupdf.open(pdf_path) as document:  # type: ignore[no-untyped-call]
        return [
            PaperPage(page=index + 1, text=page.get_text("text"))
            for index, page in enumerate(document)
        ]


def _validate_claim_evidence(spec: PaperSpec, pages: list[PaperPage]) -> PaperSpec:
    page_text = {page.page: _normalize_text(page.text) for page in pages}
    accepted: list[PaperClaim] = []
    accepted_results: list[PaperResult] = []
    unresolved = list(spec.unresolved_fields)

    for claim in spec.claims:
        normalized_evidence = _normalize_text(claim.evidence_text)
        field_root = claim.field.partition(".")[0]
        if field_root in REPRODUCTION_FIELD_ROOTS and normalized_evidence in page_text.get(
            claim.page, ""
        ):
            accepted.append(claim)
        elif claim.field not in unresolved:
            unresolved.append(claim.field)

    for result in spec.reported_results:
        normalized_evidence = _normalize_text(result.evidence_text)
        unresolved_name = f"result.{result.metric}"
        if normalized_evidence in page_text.get(result.page, ""):
            accepted_results.append(result)
        elif unresolved_name not in unresolved:
            unresolved.append(unresolved_name)

    return PaperSpec(
        claims=accepted,
        reported_results=accepted_results,
        unresolved_fields=unresolved,
    )


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()
