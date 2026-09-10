from __future__ import annotations

import json
import mimetypes
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from repropilot.artifacts import ArtifactStore
from repropilot.domain import ApprovalDecision, RunRequest
from repropilot.orchestrator import ReproPilot
from repropilot.services import DefaultRunServices
from repropilot.settings import load_run_request


class RunExecutor(Protocol):
    def run(self, request: RunRequest) -> Path: ...

    def resume(self, run_dir: Path, approval: ApprovalDecision) -> Path: ...


class OrchestratorExecutor:
    def __init__(
        self,
        output_root: Path,
        services_factory: Callable[[], DefaultRunServices],
    ) -> None:
        self.output_root = output_root
        self.services_factory = services_factory

    def run(self, request: RunRequest) -> Path:
        return ReproPilot(self.output_root, self.services_factory()).run(request).run_dir

    def resume(self, run_dir: Path, approval: ApprovalDecision) -> Path:
        return ReproPilot(
            self.output_root, self.services_factory()
        ).resume(run_dir, approval).run_dir


@dataclass
class _Job:
    status: str = "QUEUED"
    run_id: str | None = None
    error: str | None = None


class LocalRunServer:
    """Loopback-only HTTP adapter around the existing ReproPilot orchestrator."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        output_root: Path,
        runner: RunExecutor,
        static_root: Path | None = None,
    ) -> None:
        if host not in {"127.0.0.1", "::1", "localhost"}:
            raise ValueError("The local API must bind to a loopback host")
        self.output_root = output_root.resolve()
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.static_root = static_root.resolve() if static_root else None
        self._jobs: dict[str, _Job] = {}
        self._jobs_lock = threading.Lock()
        handler = self._handler()
        self._server = ThreadingHTTPServer((host, port), handler)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def serve_forever(self) -> None:
        self._server.serve_forever()

    def shutdown(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def wait_for_job(self, job_id: str, *, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._jobs_lock:
                job = self._jobs.get(job_id)
                if job is not None and job.status not in {"QUEUED", "RUNNING"}:
                    return
            time.sleep(0.01)
        raise TimeoutError(f"Job {job_id} did not finish within {timeout} seconds")

    def _new_job(self, work: Callable[[], Path]) -> str:
        job_id = uuid4().hex
        with self._jobs_lock:
            self._jobs[job_id] = _Job()

        def execute() -> None:
            with self._jobs_lock:
                self._jobs[job_id].status = "RUNNING"
            try:
                run_dir = work()
                metadata = ArtifactStore(run_dir).read_metadata()
                with self._jobs_lock:
                    job = self._jobs[job_id]
                    job.run_id = run_dir.name
                    job.status = str(metadata["status"])
            except Exception as exc:
                with self._jobs_lock:
                    job = self._jobs[job_id]
                    job.status = "FAILED"
                    job.error = str(exc)

        threading.Thread(target=execute, daemon=True).start()
        return job_id

    def _run_path(self, run_id: str) -> Path | None:
        if re.fullmatch(r"[A-Za-z0-9_-]+", run_id) is None:
            return None
        run_dir = (self.output_root / run_id).resolve()
        if run_dir.parent != self.output_root or not run_dir.is_dir():
            return None
        return run_dir

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        application = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "ReproPilotLocal/0.1"

            def do_GET(self) -> None:  # noqa: N802
                path = unquote(urlsplit(self.path).path)
                if path == "/api/health":
                    self._json(HTTPStatus.OK, {"status": "ok", "mode": "local"})
                    return
                if path.startswith("/api/jobs/"):
                    self._job(path.removeprefix("/api/jobs/"))
                    return
                match = re.fullmatch(r"/api/runs/([^/]+)(?:/(events|report))?", path)
                if match:
                    self._run(match.group(1), match.group(2))
                    return
                if path.startswith("/api/"):
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                self._static(path)

            def do_POST(self) -> None:  # noqa: N802
                content_type = self.headers.get("Content-Type", "").split(";", 1)[0]
                if content_type.strip().lower() != "application/json":
                    self._json(
                        HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                        {"error": "application_json_required"},
                    )
                    return
                path = unquote(urlsplit(self.path).path)
                if path == "/api/runs":
                    self._create_run()
                    return
                match = re.fullmatch(r"/api/runs/([^/]+)/decision", path)
                if match:
                    self._decide(match.group(1))
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

            def log_message(self, format: str, *args: object) -> None:
                return

            def _body(self) -> dict[str, Any] | None:
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    length = 0
                if length <= 0 or length > 65_536:
                    return None
                try:
                    value = json.loads(self.rfile.read(length))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return None
                return cast(dict[str, Any], value) if isinstance(value, dict) else None

            def _create_run(self) -> None:
                body = self._body()
                config_path = body.get("config_path") if body else None
                if not isinstance(config_path, str):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "config_path_required"})
                    return
                try:
                    request = load_run_request(Path(config_path).expanduser().resolve())
                except (OSError, ValueError) as exc:
                    self._json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "invalid_config", "detail": str(exc)},
                    )
                    return
                job_id = application._new_job(lambda: application.runner.run(request))
                self._json(HTTPStatus.ACCEPTED, {"job_id": job_id})

            def _decide(self, run_id: str) -> None:
                run_dir = application._run_path(run_id)
                body = self._body()
                if run_dir is None or body is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                approved = body.get("approved")
                reason = body.get("reason")
                if not isinstance(approved, bool) or (
                    not approved and (not isinstance(reason, str) or not reason.strip())
                ):
                    self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid_decision"})
                    return
                try:
                    pending = ArtifactStore(run_dir).read_metadata_from("pending_patch.json")
                    approval = ApprovalDecision(
                        patch_id=str(pending["patch_id"]),
                        patch_sha256=str(pending["patch_sha256"]),
                        approved=approved,
                        reason=reason if isinstance(reason, str) else None,
                    )
                except (OSError, KeyError, ValueError) as exc:
                    self._json(
                        HTTPStatus.CONFLICT,
                        {"error": "decision_unavailable", "detail": str(exc)},
                    )
                    return
                ArtifactStore(run_dir).write_json_artifact(
                    "approval.json", approval.model_dump(mode="json")
                )
                job_id = application._new_job(
                    lambda: application.runner.resume(run_dir, approval)
                )
                self._json(HTTPStatus.ACCEPTED, {"job_id": job_id})

            def _job(self, job_id: str) -> None:
                with application._jobs_lock:
                    job = application._jobs.get(job_id)
                    payload = None if job is None else {
                        "job_id": job_id,
                        "status": job.status,
                        "run_id": job.run_id,
                        "error": job.error,
                    }
                if payload is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                self._json(HTTPStatus.OK, payload)

            def _run(self, run_id: str, resource: str | None) -> None:
                run_dir = application._run_path(run_id)
                if run_dir is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                store = ArtifactStore(run_dir)
                if resource == "events":
                    events = [
                        event.model_dump(mode="json") for event in store.read_events()
                    ]
                    self._json(
                        HTTPStatus.OK,
                        {"events": events},
                    )
                    return
                if resource == "report":
                    self._file(run_dir / "report.html", "text/html; charset=utf-8")
                    return
                metadata = store.read_metadata()
                metadata["event_count"] = len(store.read_events())
                metadata["report_url"] = (
                    f"/api/runs/{run_id}/report"
                    if (run_dir / "report.html").exists()
                    else None
                )
                self._json(HTTPStatus.OK, metadata)

            def _static(self, path: str) -> None:
                root = application.static_root
                if root is None:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                relative = "index.html" if path == "/" else path.lstrip("/")
                candidate = (root / relative).resolve()
                if candidate.parent != root and root not in candidate.parents:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                if not candidate.is_file():
                    candidate = root / "index.html"
                mime_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                self._file(candidate, mime_type)

            def _file(self, path: Path, content_type: str) -> None:
                try:
                    content = path.read_bytes()
                except OSError:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                    return
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

            def _json(self, status: HTTPStatus, payload: object) -> None:
                content = json.dumps(payload, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)

        return Handler
