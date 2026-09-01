from __future__ import annotations

import json
import re
import time
import unicodedata
from pathlib import Path
from typing import Protocol

import pymupdf
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam
from openai.types.shared_params import ResponseFormatJSONObject
from pydantic import ValidationError

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
    def __init__(
        self,
        client: OpenAI,
        model: str,
        *,
        structured_output_mode: str = "json_schema",
    ) -> None:
        self.client = client
        self.model = model
        self.structured_output_mode = structured_output_mode

    def extract(self, pages: list[PaperPage]) -> PaperExtraction:
        page_text = "\n\n".join(f"[PAGE {page.page}]\n{page.text}" for page in pages)
        started_at = time.perf_counter()
        messages: list[ChatCompletionMessageParam] = [
            {"role": "system", "content": PAPER_EXTRACTION_PROMPT},
            {"role": "user", "content": page_text},
        ]
        if self.structured_output_mode == "json_object":
            messages.append(
                {
                    "role": "system",
                    "content": (
                        "Return valid JSON matching this JSON schema: "
                        + json.dumps(PaperSpec.model_json_schema())
                    ),
                }
            )
            response_format: ResponseFormatJSONObject = {"type": "json_object"}
            parsed = None
            content: str | None = None
            validation_error = ""
            for attempt in range(2):
                completion = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    response_format=response_format,
                    extra_body={"thinking": {"type": "disabled"}},
                    max_tokens=8192,
                )
                content = completion.choices[0].message.content
                try:
                    parsed = PaperSpec.model_validate_json(content) if content else None
                except ValidationError as exc:
                    validation_error = str(exc)
                if parsed is not None:
                    break
                if attempt == 0:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "The JSON did not match the schema. Return corrected JSON. "
                                "Claims without a non-empty exact quote and integer page must "
                                "be removed and named in unresolved_fields. Error: "
                                + validation_error[:2000]
                            ),
                        }
                    )
            if parsed is None and content:
                parsed = _salvage_paper_spec(content)
        else:
            completion = self.client.chat.completions.parse(
                model=self.model,
                messages=messages,
                response_format=PaperSpec,
            )
            parsed = completion.choices[0].message.parsed
        duration_seconds = time.perf_counter() - started_at
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


def _salvage_paper_spec(content: str) -> PaperSpec | None:
    try:
        payload = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None

    raw_unresolved = payload.get("unresolved_fields", [])
    unresolved = (
        [value for value in raw_unresolved if isinstance(value, str) and value]
        if isinstance(raw_unresolved, list)
        else []
    )
    claims: list[PaperClaim] = []
    raw_claims = payload.get("claims", [])
    if isinstance(raw_claims, list):
        for value in raw_claims:
            try:
                claims.append(PaperClaim.model_validate(value))
            except ValidationError:
                if isinstance(value, dict):
                    field = value.get("field")
                    if isinstance(field, str) and field and field not in unresolved:
                        unresolved.append(field)

    results: list[PaperResult] = []
    raw_results = payload.get("reported_results", [])
    if isinstance(raw_results, list):
        for value in raw_results:
            try:
                results.append(PaperResult.model_validate(value))
            except ValidationError:
                if isinstance(value, dict):
                    metric = value.get("metric")
                    unresolved_name = f"result.{metric}" if isinstance(metric, str) else ""
                    if unresolved_name and unresolved_name not in unresolved:
                        unresolved.append(unresolved_name)

    return PaperSpec(
        claims=claims,
        reported_results=results,
        unresolved_fields=unresolved,
    )
