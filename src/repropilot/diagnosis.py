from __future__ import annotations

import re

from repropilot.domain import Diagnosis, DiagnosisCategory

PATTERNS: tuple[tuple[DiagnosisCategory, re.Pattern[str]], ...] = (
    (DiagnosisCategory.DEPENDENCY, re.compile(r"ModuleNotFoundError|No module named", re.I)),
    (DiagnosisCategory.PATH, re.compile(r"FileNotFoundError|No such file|does not exist", re.I)),
    (DiagnosisCategory.CUDA_RUNTIME, re.compile(r"CUDA|cuDNN|NVIDIA driver", re.I)),
    (DiagnosisCategory.METRIC, re.compile(r"macro|micro|metric|F1", re.I)),
    (DiagnosisCategory.DATA, re.compile(r"dataset|dataloader|data loader", re.I)),
    (DiagnosisCategory.CONFIGURATION, re.compile(r"config|yaml|toml|argument", re.I)),
)


def diagnose_failure(
    command: list[str],
    log_tail: str,
    implicated_files: list[str],
) -> Diagnosis:
    del command
    lines = [line.strip() for line in log_tail.splitlines() if line.strip()]
    for category, pattern in PATTERNS:
        for line in lines:
            if pattern.search(line):
                return Diagnosis(
                    category=category,
                    root_cause=line,
                    evidence=[line],
                    related_files=implicated_files,
                    confidence=0.9,
                )

    fallback = next(
        (line for line in lines if re.search(r"error|exception|crash|failed", line, re.I)),
        lines[-1] if lines else "No diagnostic log evidence was available.",
    )
    return Diagnosis(
        category=DiagnosisCategory.UNKNOWN,
        root_cause=fallback,
        evidence=[fallback],
        related_files=implicated_files,
        confidence=0.3,
    )
