from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from repropilot.cli import _default_services
from repropilot.domain import Diagnosis, DiagnosisCategory, PaperPage
from repropilot.paper import OpenAICompatiblePaperLLM
from repropilot.services import (
    DefaultRunServices,
    OpenAICompatiblePatchGenerator,
    PatchDraft,
)


class JsonObjectCompletions:
    def __init__(self, content: str | list[str]) -> None:
        self.contents = [content] if isinstance(content, str) else content
        self.kwargs: dict[str, Any] = {}
        self.call_count = 0

    def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        content = self.contents[min(self.call_count, len(self.contents) - 1)]
        self.call_count += 1
        return SimpleNamespace(
            model="deepseek-v4-pro",
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )

    def parse(self, **kwargs: Any) -> Any:
        raise AssertionError("DeepSeek JSON mode must not call chat.completions.parse")


class ParsedCompletions:
    def __init__(self, payloads: list[dict[str, Any]]) -> None:
        self.payloads = payloads
        self.call_count = 0

    def create(self, **kwargs: Any) -> Any:
        raise AssertionError("Native structured output must not call create")

    def parse(self, **kwargs: Any) -> Any:
        payload = self.payloads[min(self.call_count, len(self.payloads) - 1)]
        self.call_count += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(parsed=PatchDraft.model_validate(payload)))
            ]
        )


def test_deepseek_json_mode_validates_a_paper_spec() -> None:
    payload = {
        "claims": [],
        "reported_results": [],
        "unresolved_fields": ["training.random_seed"],
    }
    completions = JsonObjectCompletions(json.dumps(payload))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatiblePaperLLM(
        client,
        "deepseek-v4-pro",
        structured_output_mode="json_object",
    )

    extraction = llm.extract([PaperPage(page=1, text="A tiny paper.")])

    assert extraction.spec.unresolved_fields == ["training.random_seed"]
    assert extraction.usage.input_tokens == 11
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "json" in completions.kwargs["messages"][-1]["content"].casefold()


def test_deepseek_paper_json_retries_one_schema_error() -> None:
    invalid = {
        "claims": [
            {
                "field": "training.random_seed",
                "value": None,
                "evidence_text": "",
                "page": None,
            }
        ],
        "reported_results": [],
        "unresolved_fields": [],
    }
    valid = {
        "claims": [],
        "reported_results": [],
        "unresolved_fields": ["training.random_seed"],
    }
    completions = JsonObjectCompletions([json.dumps(invalid), json.dumps(valid)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatiblePaperLLM(
        client,
        "deepseek-v4-pro",
        structured_output_mode="json_object",
    )

    extraction = llm.extract([PaperPage(page=1, text="A tiny paper.")])

    assert completions.call_count == 2
    assert extraction.spec.unresolved_fields == ["training.random_seed"]


def test_deepseek_paper_json_salvages_invalid_claim_as_unresolved() -> None:
    invalid = {
        "claims": [
            {
                "field": "training.random_seed",
                "value": None,
                "evidence_text": "",
                "page": None,
            }
        ],
        "reported_results": [],
        "unresolved_fields": [],
    }
    completions = JsonObjectCompletions([json.dumps(invalid), json.dumps(invalid)])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatiblePaperLLM(
        client,
        "deepseek-v4-pro",
        structured_output_mode="json_object",
    )

    extraction = llm.extract([PaperPage(page=1, text="No seed is specified.")])

    assert completions.call_count == 2
    assert extraction.spec.claims == []
    assert extraction.spec.unresolved_fields == ["training.random_seed"]


def test_deepseek_recovers_claims_after_a_result_only_response() -> None:
    result_only = {
        "claims": [],
        "reported_results": [
            {
                "metric": "Error",
                "value": 8.75,
                "unit": "%",
                "evidence_text": "ResNet 20 0.27M 8.75",
                "page": 7,
                "confidence": 0.98,
            }
        ],
        "unresolved_fields": ["dataset.name", "training.seed"],
    }
    claims_only = {
        "claims": [
            {
                "field": "dataset.name",
                "value": "CIFAR-10",
                "evidence_text": "CIFAR-10",
                "page": 1,
                "confidence": 0.99,
            }
        ],
        "reported_results": [],
        "unresolved_fields": ["training.seed"],
    }
    completions = JsonObjectCompletions(
        [json.dumps(result_only), json.dumps(claims_only)]
    )
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    llm = OpenAICompatiblePaperLLM(
        client,
        "deepseek-v4-pro",
        structured_output_mode="json_object",
    )

    extraction = llm.extract(
        [
            PaperPage(page=1, text="Experiments use CIFAR-10."),
            PaperPage(page=7, text="ResNet 20 0.27M 8.75"),
        ]
    )

    assert completions.call_count == 2
    assert extraction.spec.claims[0].field == "dataset.name"
    assert extraction.spec.reported_results[0].value == 8.75
    assert extraction.spec.unresolved_fields == ["training.seed"]
    assert extraction.usage.input_tokens == 22
    assert extraction.usage.output_tokens == 14


def test_deepseek_json_mode_validates_a_patch_draft(tmp_path: Path) -> None:
    trainer = tmp_path / "trainer.py"
    trainer.write_text("model.cuda()\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    payload = {
        "edits": [
            {
                "path": "trainer.py",
                "search": "model.cuda()\n",
                "replacement": "model.cpu()\n",
            }
        ],
        "explanation": "Use the requested CPU device.",
        "targeted_test": ["python trainer.py --help"],
    }
    completions = JsonObjectCompletions(json.dumps(payload))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    generator = OpenAICompatiblePatchGenerator(
        client,
        "deepseek-v4-pro",
        structured_output_mode="json_object",
    )
    diagnosis = Diagnosis(
        category=DiagnosisCategory.CUDA_RUNTIME,
        root_cause="CUDA is unavailable in the CPU sandbox.",
        evidence=["Torch not compiled with CUDA enabled"],
        related_files=["trainer.py"],
        confidence=0.99,
    )

    proposal = generator.propose(diagnosis, tmp_path, "CUDA failure")

    assert proposal.allowed_paths == ["trainer.py"]
    assert proposal.targeted_test == ["python", "trainer.py", "--help"]
    assert "-model.cuda()" in proposal.diff
    assert "+model.cpu()" in proposal.diff
    completed = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=tmp_path,
        input=proposal.diff,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completions.kwargs["response_format"] == {"type": "json_object"}
    assert completions.kwargs["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "json" in completions.kwargs["messages"][-1]["content"].casefold()
    assert "map_location" in completions.kwargs["messages"][0]["content"]
    assert len(generator.usage) == 1
    assert generator.usage[0].model == "deepseek-v4-pro"
    assert generator.usage[0].input_tokens == 11
    assert generator.usage[0].output_tokens == 7
    assert generator.usage[0].duration_seconds >= 0
    assert generator.usage[0].estimated_cost_usd is None


def test_patch_generator_retries_one_invalid_git_diff(tmp_path: Path) -> None:
    trainer = tmp_path / "trainer.py"
    trainer.write_text("model.cuda()\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    invalid = {
        "diff": "--- a/trainer.py\n+++ b/trainer.py\n@@ -1 +1 @@\n-old\n+new\n",
        "explanation": "First draft is malformed.",
        "targeted_test": ["python", "trainer.py", "--help"],
        "allowed_paths": ["trainer.py"],
    }
    valid = {
        "diff": (
            "diff --git a/trainer.py b/trainer.py\n"
            "--- a/trainer.py\n"
            "+++ b/trainer.py\n"
            "@@ -1 +1 @@\n"
            "-model.cuda()\n"
            "+model.cpu()\n"
        ),
        "explanation": "Second draft is applicable.",
        "targeted_test": ["python", "trainer.py", "--help"],
        "allowed_paths": ["trainer.py"],
    }
    completions = ParsedCompletions([invalid, valid])
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    generator = OpenAICompatiblePatchGenerator(
        client,
        "gpt-test",
        structured_output_mode="json_schema",
    )
    diagnosis = Diagnosis(
        category=DiagnosisCategory.CUDA_RUNTIME,
        root_cause="CUDA is unavailable.",
        evidence=["Torch not compiled with CUDA enabled"],
        related_files=["trainer.py"],
        confidence=0.99,
    )

    proposal = generator.propose(diagnosis, tmp_path, "CUDA failure")

    assert completions.call_count == 2
    assert proposal.diff == valid["diff"]
    assert len(generator.usage) == 2
    assert all(item.input_tokens == 0 for item in generator.usage)


def test_deepseek_base_url_selects_json_object_mode(monkeypatch: Any) -> None:
    for variable in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.deepseek.com")

    services = _default_services()

    assert services.paper_llm.structured_output_mode == "json_object"
    assert services.patch_generator.structured_output_mode == "json_object"


def test_git_combines_rolled_back_patch_progress_without_touching_worktree(
    tmp_path: Path,
) -> None:
    original = "".join(f"line {number}\n" for number in range(1, 21))
    tracked = tmp_path / "trainer.py"
    tracked.write_text(original, encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "trainer.py"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    first = (
        "diff --git a/trainer.py b/trainer.py\n"
        "--- a/trainer.py\n"
        "+++ b/trainer.py\n"
        "@@ -1,3 +1,3 @@\n"
        " line 1\n"
        "-line 2\n"
        "+LINE 2\n"
        " line 3\n"
    )
    second = (
        "diff --git a/trainer.py b/trainer.py\n"
        "--- a/trainer.py\n"
        "+++ b/trainer.py\n"
        "@@ -17,3 +17,3 @@\n"
        " line 17\n"
        "-line 18\n"
        "+LINE 18\n"
        " line 19\n"
    )

    combined = DefaultRunServices._combine_diffs(tmp_path, [first, second])

    assert "-line 2" in combined and "+LINE 2" in combined
    assert "-line 18" in combined and "+LINE 18" in combined
    assert tracked.read_text(encoding="utf-8") == original
    completed = subprocess.run(
        ["git", "apply", "--check", "-"],
        cwd=tmp_path,
        input=combined,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_temporary_repair_worktree_exposes_prior_progress_only_inside_context(
    tmp_path: Path,
) -> None:
    tracked = tmp_path / "trainer.py"
    tracked.write_text("model.cuda()\ncheckpoint = torch.load(path)\n", encoding="utf-8")
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "add", "trainer.py"], cwd=tmp_path, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-m",
            "baseline",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    first = (
        "diff --git a/trainer.py b/trainer.py\n"
        "--- a/trainer.py\n"
        "+++ b/trainer.py\n"
        "@@ -1,2 +1,2 @@\n"
        "-model.cuda()\n"
        "+model.cpu()\n"
        " checkpoint = torch.load(path)\n"
    )

    with DefaultRunServices._temporary_patched_worktree(tmp_path, [first]) as patched:
        assert (patched / "trainer.py").read_text(encoding="utf-8").startswith(
            "model.cpu()"
        )
        assert tracked.read_text(encoding="utf-8").startswith("model.cuda()")

    assert tracked.read_text(encoding="utf-8").startswith("model.cuda()")
