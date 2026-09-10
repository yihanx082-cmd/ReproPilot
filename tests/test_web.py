from __future__ import annotations

import hashlib
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from repropilot.artifacts import ArtifactStore
from repropilot.domain import RunRequest, RunStatus
from repropilot.web import LocalRunServer


class SuccessfulRunner:
    def run(self, request: RunRequest) -> Path:
        store = ArtifactStore.create(self.output_root, request)
        store.update_metadata(status=RunStatus.SUCCEEDED.value)
        store.run_dir.joinpath("report.html").write_text("<h1>report</h1>", encoding="utf-8")
        return store.run_dir

    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def resume(self, run_dir: Path, approval: object) -> Path:
        ArtifactStore(run_dir).update_metadata(status=RunStatus.SUCCEEDED.value)
        run_dir.joinpath("report.html").write_text("<h1>report</h1>", encoding="utf-8")
        return run_dir


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: object | None = None,
) -> tuple[int, dict[str, object]]:
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_local_api_creates_run_and_exposes_status(tmp_path: Path) -> None:
    config = tmp_path / "run.yaml"
    config.write_text(
        """
paper: paper.pdf
repository: repo
dataset: {name: sample, path: data}
command: [python, train.py]
environment: {python: '3.11', device: cpu}
""".strip(),
        encoding="utf-8",
    )
    output_root = tmp_path / "runs"
    server = LocalRunServer(
        host="127.0.0.1",
        port=0,
        output_root=output_root,
        runner=SuccessfulRunner(output_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base_url = f"http://127.0.0.1:{server.port}"
        status, created = request_json(
            f"{base_url}/api/runs",
            method="POST",
            payload={"config_path": str(config)},
        )
        assert status == 202
        job_id = str(created["job_id"])
        server.wait_for_job(job_id, timeout=5)

        status, job = request_json(f"{base_url}/api/jobs/{job_id}")
        assert status == 200
        assert job["status"] == "SUCCEEDED"
        run_id = str(job["run_id"])

        status, run = request_json(f"{base_url}/api/runs/{run_id}")
        assert status == 200
        assert run["status"] == "SUCCEEDED"
        assert run["report_url"] == f"/api/runs/{run_id}/report"
        assert (output_root / run_id / "run.json").exists()
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_local_api_rejects_non_loopback_binding(tmp_path: Path) -> None:
    runner = SuccessfulRunner(tmp_path / "runs")
    try:
        LocalRunServer(host="0.0.0.0", port=0, output_root=tmp_path / "runs", runner=runner)
    except ValueError as exc:
        assert "loopback" in str(exc)
    else:
        raise AssertionError("non-loopback server binding must be rejected")


def test_local_api_rejects_run_path_traversal(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    server = LocalRunServer(
        host="127.0.0.1",
        port=0,
        output_root=output_root,
        runner=SuccessfulRunner(output_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, error = request_json(
            f"http://127.0.0.1:{server.port}/api/runs/..%2Fsecret"
        )
        assert status == 404
        assert error["error"] == "not_found"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_local_api_records_sha_bound_decision_before_resume(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    request = RunRequest.model_validate(
        {
            "paper": "paper.pdf",
            "repository": "repo",
            "dataset": {"name": "sample", "path": "data"},
            "command": ["python", "train.py"],
        }
    )
    store = ArtifactStore.create(output_root, request)
    store.update_metadata(status=RunStatus.WAITING_APPROVAL.value)
    patch_sha256 = hashlib.sha256(b"diff").hexdigest()
    store.write_json_artifact(
        "pending_patch.json",
        {"patch_id": "patch-1", "patch_sha256": patch_sha256},
    )
    server = LocalRunServer(
        host="127.0.0.1",
        port=0,
        output_root=output_root,
        runner=SuccessfulRunner(output_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, created = request_json(
            f"http://127.0.0.1:{server.port}/api/runs/{store.run_dir.name}/decision",
            method="POST",
            payload={"approved": True, "reason": None},
        )
        assert status == 202
        server.wait_for_job(str(created["job_id"]), timeout=5)
        approval = store.read_metadata_from("approval.json")
        assert approval["patch_id"] == "patch-1"
        assert approval["patch_sha256"] == patch_sha256
        assert approval["approved"] is True
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_local_api_requires_json_for_mutations(tmp_path: Path) -> None:
    output_root = tmp_path / "runs"
    server = LocalRunServer(
        host="127.0.0.1",
        port=0,
        output_root=output_root,
        runner=SuccessfulRunner(output_root),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{server.port}/api/runs",
            data=json.dumps({"config_path": "run.yaml"}).encode(),
            method="POST",
            headers={"Content-Type": "text/plain"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request, timeout=5)
        assert error.value.code == 415
    finally:
        server.shutdown()
        thread.join(timeout=5)
