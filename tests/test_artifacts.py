from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError


def _contracts():
    try:
        from repropilot.artifacts import ArtifactStore
        from repropilot.domain import EvidenceEvent, RunRequest
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task 1 contracts are not implemented: {exc}")
    return ArtifactStore, EvidenceEvent, RunRequest


def valid_request(tmp_path: Path) -> dict[str, object]:
    return {
        "paper": str(tmp_path / "paper.pdf"),
        "repository": "https://github.com/example/project.git",
        "dataset": {"name": "CIFAR-10", "path": str(tmp_path / "data")},
        "command": ["python", "train.py", "--epochs", "1"],
        "environment": {"python": "3.11", "device": "cpu"},
    }


def test_run_request_rejects_more_than_three_patch_attempts(tmp_path: Path):
    _, _, RunRequest = _contracts()
    request = valid_request(tmp_path)
    request["limits"] = {"max_patch_attempts": 4}

    with pytest.raises(ValidationError):
        RunRequest.model_validate(request)


def test_run_request_accepts_a_cited_three_seed_formal_experiment(tmp_path: Path):
    _, _, RunRequest = _contracts()
    request = valid_request(tmp_path)
    request["formal_experiment"] = {
        "command": ["python", "train.py", "--seed", "{seed}"],
        "seeds": [11, 22, 33],
        "comparison_scope": "paper",
        "scope_evidence": ["paper_spec.json#results[0]", "repo_facts.json#model"],
    }

    parsed = RunRequest.model_validate(request)

    assert parsed.formal_experiment is not None
    assert parsed.formal_experiment.seeds == [11, 22, 33]


@pytest.mark.parametrize(
    "formal_experiment",
    [
        {
            "command": ["python", "train.py", "--seed", "{seed}"],
            "seeds": [11, 22],
        },
        {
            "command": ["python", "train.py", "--seed", "{seed}"],
            "seeds": [11, 11, 22],
        },
        {
            "command": ["python", "train.py", "--seed", "11"],
            "seeds": [11, 22, 33],
        },
        {
            "command": ["python", "train.py", "--seed", "{seed}"],
            "seeds": [11, 22, 33],
            "comparison_scope": "paper",
        },
    ],
)
def test_run_request_rejects_unverifiable_formal_experiments(
    tmp_path: Path, formal_experiment: dict[str, object]
) -> None:
    _, _, RunRequest = _contracts()
    request = valid_request(tmp_path)
    request["formal_experiment"] = formal_experiment

    with pytest.raises(ValidationError):
        RunRequest.model_validate(request)


def test_artifact_events_are_append_only(tmp_path: Path):
    ArtifactStore, EvidenceEvent, RunRequest = _contracts()
    store = ArtifactStore.create(
        tmp_path / "runs", RunRequest.model_validate(valid_request(tmp_path))
    )

    store.append_event(EvidenceEvent(kind="state", message="INGEST"))
    store.append_event(EvidenceEvent(kind="state", message="AUDIT"))

    assert [event.message for event in store.read_events()] == ["INGEST", "AUDIT"]
    event_lines = store.events_path.read_text(encoding="utf-8").splitlines()
    assert len(event_lines) == 2
    assert [json.loads(line)["message"] for line in event_lines] == [
        "INGEST",
        "AUDIT",
    ]


def test_create_writes_run_metadata_without_overwriting_another_run(tmp_path: Path):
    ArtifactStore, _, RunRequest = _contracts()
    request = RunRequest.model_validate(valid_request(tmp_path))

    first = ArtifactStore.create(tmp_path / "runs", request)
    second = ArtifactStore.create(tmp_path / "runs", request)

    assert first.run_dir != second.run_dir
    assert json.loads(first.run_path.read_text(encoding="utf-8"))["status"] == "CREATED"
    assert first.events_path.read_text(encoding="utf-8") == ""
