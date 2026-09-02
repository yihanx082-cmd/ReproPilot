from __future__ import annotations

import subprocess
import sys


def test_training_contract() -> None:
    result = subprocess.run(
        [sys.executable, "train.py"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "macro_f1=1.0" in result.stdout
