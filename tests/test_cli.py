from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

runner = CliRunner()


def _app():
    try:
        from repropilot.cli import app
    except ModuleNotFoundError as exc:
        pytest.fail(f"Task 1 CLI is not implemented: {exc}")
    return app


def write_config(path: Path, tmp_path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "paper": str(tmp_path / "paper.pdf"),
                "repository": "https://github.com/example/project.git",
                "dataset": {"name": "CIFAR-10", "path": str(tmp_path / "data")},
                "command": ["python", "train.py", "--epochs", "1"],
                "environment": {"python": "3.11", "device": "cpu"},
            }
        ),
        encoding="utf-8",
    )


def test_run_creates_a_valid_run_that_inspect_can_read(tmp_path: Path):
    app = _app()
    config_path = tmp_path / "run.yaml"
    output_root = tmp_path / "runs"
    write_config(config_path, tmp_path)

    run_result = runner.invoke(
        app,
        [
            "run",
            "--config",
            str(config_path),
            "--output-root",
            str(output_root),
            "--validate-only",
        ],
    )

    assert run_result.exit_code == 0, run_result.output
    run_dirs = list(output_root.iterdir())
    assert len(run_dirs) == 1

    inspect_result = runner.invoke(app, ["inspect", str(run_dirs[0])])
    assert inspect_result.exit_code == 0, inspect_result.output
    assert "CREATED" in inspect_result.output
    assert "Events: 0" in inspect_result.output


def test_run_rejects_invalid_config_before_creating_artifacts(tmp_path: Path):
    app = _app()
    config_path = tmp_path / "invalid.yaml"
    output_root = tmp_path / "runs"
    config_path.write_text("limits:\n  max_patch_attempts: 4\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["run", "--config", str(config_path), "--output-root", str(output_root)],
    )

    assert result.exit_code != 0
    assert not output_root.exists()


def test_approve_records_a_sha_bound_decision(tmp_path: Path):
    app = _app()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    diff = "diff --git a/x b/x\n"
    patch_sha256 = hashlib.sha256(diff.encode()).hexdigest()
    (run_dir / "pending_patch.json").write_text(
        json.dumps({"patch_id": "patch-1", "patch_sha256": patch_sha256, "diff": diff}),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["approve", str(run_dir), "patch-1"])

    assert result.exit_code == 0, result.output
    approval = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
    assert approval == {
        "approved": True,
        "patch_id": "patch-1",
        "patch_sha256": patch_sha256,
        "reason": None,
    }


def test_reject_requires_and_records_a_reason(tmp_path: Path):
    app = _app()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    diff = "diff --git a/x b/x\n"
    patch_sha256 = hashlib.sha256(diff.encode()).hexdigest()
    (run_dir / "pending_patch.json").write_text(
        json.dumps({"patch_id": "patch-1", "patch_sha256": patch_sha256, "diff": diff}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["reject", str(run_dir), "patch-1", "--reason", "Metric semantics differ."],
    )

    assert result.exit_code == 0, result.output
    approval = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
    assert approval["approved"] is False
    assert approval["reason"] == "Metric semantics differ."
