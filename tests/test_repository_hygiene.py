from __future__ import annotations

import re
import subprocess
from pathlib import Path

SENSITIVE_PATTERNS = (
    re.compile("s" + r"k-[A-Za-z0-9_-]{20,}"),
    re.compile("gh" + r"[opusr]_[A-Za-z0-9]{20,}"),
    re.compile("github" + r"_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(
        r"[A-Za-z]:(?:\\|/)(?:Users(?:\\|/)[A-Za-z0-9._-]+|Projects|Work|Desktop|Documents)(?:\\|/)",
        re.I,
    ),
)


def _contains_sensitive_value(content: str) -> bool:
    return any(pattern.search(content) for pattern in SENSITIVE_PATTERNS)


def test_hygiene_patterns_cover_tokens_and_both_windows_path_styles() -> None:
    sensitive_samples = [
        "s" + "k-" + "a" * 24,
        "gh" + "o_" + "a" * 24,
        "github" + "_pat_" + "a" * 24,
        "AKIA" + "A" * 16,
        "C:" + "\\Users\\example\\paper.pdf",
        "D:" + "/Projects/example/train.py",
    ]
    ordinary_samples = [
        "https://github.com/example/project",
        "sk-short-placeholder",
        "D:relative/path.py",
    ]

    assert all(_contains_sensitive_value(sample) for sample in sensitive_samples)
    assert not any(_contains_sensitive_value(sample) for sample in ordinary_samples)


def test_tracked_files_do_not_contain_credentials_or_private_windows_paths() -> None:
    root = Path(__file__).parents[1]
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    paths = [Path(item.decode()) for item in completed.stdout.split(b"\0") if item]
    findings: list[str] = []
    for relative in paths:
        try:
            content = (root / relative).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if _contains_sensitive_value(content):
            findings.append(relative.as_posix())

    assert findings == []
