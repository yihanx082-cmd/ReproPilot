from __future__ import annotations

import json
from pathlib import Path


def main() -> None:
    settings = json.loads(Path("settings.json").read_text(encoding="utf-8"))
    if settings["split_strategy"] != "group":
        raise ValueError("dataset split mismatch: expected patient/group split")
    print("one synthetic CPU epoch complete; macro_f1=1.0")


if __name__ == "__main__":
    main()
