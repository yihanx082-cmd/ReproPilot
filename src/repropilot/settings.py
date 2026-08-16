from __future__ import annotations

from pathlib import Path

import yaml

from repropilot.domain import RunRequest


def load_run_request(path: Path) -> RunRequest:
    with path.open(encoding="utf-8") as stream:
        raw_config = yaml.safe_load(stream)
    return RunRequest.model_validate(raw_config)
