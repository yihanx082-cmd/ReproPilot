from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from openai import OpenAI

from repropilot.domain import PaperPage


def test_openai_adapter_requests_and_parses_a_pydantic_paper_spec():
    try:
        from repropilot.paper import OpenAICompatiblePaperLLM
    except ImportError as exc:
        pytest.fail(f"OpenAI-compatible paper adapter is not implemented: {exc}")

    captured_requests: list[dict[str, Any]] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        captured_requests.append(json.loads(request.content))
        response_content = json.dumps(
            {
                "claims": [
                    {
                        "field": "optimizer.learning_rate",
                        "value": 0.0001,
                        "unit": None,
                        "evidence_text": "learning rate of 1e-4",
                        "page": 2,
                        "confidence": 0.98,
                    }
                ],
                "reported_results": [],
                "unresolved_fields": [],
            }
        )
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
                        "message": {"role": "assistant", "content": response_content},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )

    client = OpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handle_request)),
    )
    adapter = OpenAICompatiblePaperLLM(client=client, model="test-model")

    extraction = adapter.extract(
        [
            PaperPage(page=1, text="Abstract"),
            PaperPage(page=2, text="We use Adam with a learning rate of 1e-4."),
        ]
    )

    assert extraction.spec.claims[0].field == "optimizer.learning_rate"
    assert extraction.usage.model == "test-model"
    assert extraction.usage.input_tokens == 100
    assert extraction.usage.output_tokens == 20
    assert extraction.usage.duration_seconds >= 0
    assert extraction.usage.estimated_cost_usd is None

    request = captured_requests[0]
    assert request["model"] == "test-model"
    assert request["response_format"]["type"] == "json_schema"
    assert "[PAGE 1]\nAbstract" in request["messages"][1]["content"]
    assert "[PAGE 2]\nWe use Adam" in request["messages"][1]["content"]
