from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from repropilot.domain import EvidenceEvent, RunRequest, RunStatus


class ArtifactStore:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.run_path = run_dir / "run.json"
        self.events_path = run_dir / "events.jsonl"

    @classmethod
    def create(cls, root: Path, request: RunRequest) -> ArtifactStore:
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        run_dir = root / f"{timestamp}-{uuid4().hex[:8]}"
        run_dir.mkdir()

        store = cls(run_dir)
        metadata = {
            "run_id": run_dir.name,
            "status": RunStatus.CREATED.value,
            "request": request.model_dump(mode="json"),
        }
        store._write_json_atomically(store.run_path, metadata)
        store.events_path.touch()
        return store

    def append_event(self, event: EvidenceEvent) -> None:
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json())
            stream.write("\n")

    def read_events(self) -> list[EvidenceEvent]:
        return [
            EvidenceEvent.model_validate_json(line)
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line
        ]

    def write_json_artifact(self, filename: str, value: Any) -> Path:
        path = self.run_dir / filename
        self._write_json_atomically(path, value)
        return path

    @staticmethod
    def _write_json_atomically(path: Path, value: object) -> None:
        temporary_path = path.with_suffix(f"{path.suffix}.tmp")
        temporary_path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary_path, path)
