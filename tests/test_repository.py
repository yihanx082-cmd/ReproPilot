from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from repropilot.artifacts import ArtifactStore
from repropilot.domain import RunRequest


def _scan_repository():
    try:
        from repropilot.repository import scan_repository
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 3 repository scanner is not implemented: {exc}")
    return scan_repository


@pytest.fixture
def fixture_repository(tmp_path: Path) -> Path:
    source = Path(__file__).parent / "fixtures" / "repo_a"
    destination = tmp_path / "repo_a"
    shutil.copytree(source, destination)
    return destination


def test_scans_supported_repository_facts_with_source_locations(
    fixture_repository: Path,
):
    facts = _scan_repository()(fixture_repository)
    by_field = {fact.field: fact for fact in facts}

    assert by_field["optimizer.learning_rate"].value == 0.001
    assert by_field["optimizer.learning_rate"].source_path == "config.yaml"
    assert by_field["optimizer.learning_rate"].line_start == 2
    assert by_field["training.epochs"].value == 10
    assert by_field["training.seed"].value == 42
    assert by_field["optimizer.weight_decay"].value == 0.0005
    assert by_field["optimizer.weight_decay"].extractor == "python_ast"


def test_reports_readme_command_that_references_a_missing_script(
    fixture_repository: Path,
):
    facts = _scan_repository()(fixture_repository)

    missing = [fact for fact in facts if fact.field == "readme.missing_script"]
    assert len(missing) == 1
    assert missing[0].value == "removed_train.py"
    assert missing[0].source_path == "README.md"
    assert missing[0].line_start == 6


def test_ignores_generated_directories_and_files_larger_than_one_megabyte(
    fixture_repository: Path,
):
    for directory in ("data", "weights", ".git", ".venv"):
        ignored = fixture_repository / directory
        ignored.mkdir()
        (ignored / "ignored.yaml").write_text(
            "optimizer:\n  learning_rate: 99\n", encoding="utf-8"
        )
    (fixture_repository / "large.yaml").write_bytes(b"x" * (1024 * 1024 + 1))

    facts = _scan_repository()(fixture_repository)

    assert all(fact.value != 99 for fact in facts)
    assert all(fact.source_path != "large.yaml" for fact in facts)


def test_persists_repository_facts_deterministically(
    fixture_repository: Path, tmp_path: Path
):
    scan_repository = _scan_repository()
    store = ArtifactStore(tmp_path / "run")
    store.run_dir.mkdir()

    first = scan_repository(fixture_repository, store=store)
    first_content = (store.run_dir / "repo_facts.json").read_text(encoding="utf-8")
    second = scan_repository(fixture_repository, store=store)

    assert first == second
    assert (store.run_dir / "repo_facts.json").read_text(encoding="utf-8") == first_content


def test_extracts_canonical_facts_from_the_executed_request(tmp_path: Path) -> None:
    try:
        from repropilot.repository import execution_request_facts
    except ImportError as exc:
        pytest.fail(f"Execution request fact extraction is not implemented: {exc}")
    request = RunRequest.model_validate(
        {
            "paper": str(tmp_path / "paper.pdf"),
            "repository": str(tmp_path / "source"),
            "dataset": {"name": "CIFAR-10", "path": str(tmp_path / "data")},
            "command": [
                "python",
                "trainer.py",
                "--arch",
                "resnet20",
                "--epochs",
                "200",
                "--batch-size",
                "128",
                "--lr",
                "0.1",
                "--momentum",
                "0.9",
                "--weight-decay",
                "0.0001",
            ],
            "formal_experiment": {
                "command": ["python", "trainer.py", "--seed", "{seed}"],
                "seeds": [11, 22, 33],
            },
        }
    )

    facts = execution_request_facts(request)
    by_field = {fact.field: fact for fact in facts}

    assert by_field["dataset.name"].value == "CIFAR-10"
    assert by_field["model.architecture"].value == "resnet20"
    assert by_field["training.epochs"].value == 200
    assert by_field["training.batch_size"].value == 128
    assert by_field["optimizer.learning_rate"].value == pytest.approx(0.1)
    assert by_field["optimizer.momentum"].value == pytest.approx(0.9)
    assert by_field["optimizer.weight_decay"].value == pytest.approx(0.0001)
    assert by_field["training.seed"].value == [11, 22, 33]
    assert all(fact.source_path.startswith("run-request") for fact in facts)
    assert all(fact.extractor == "run_request" for fact in facts)
    assert all(fact.line_start >= 1 for fact in facts)
