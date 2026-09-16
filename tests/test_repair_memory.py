from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from repropilot.domain import Diagnosis, DiagnosisCategory
from repropilot.repair_memory import (
    NullRepairMemory,
    RepairExperience,
    SQLiteRepairMemory,
    build_repair_context,
)


def _diagnosis() -> Diagnosis:
    return Diagnosis(
        category=DiagnosisCategory.CONFIGURATION,
        root_cause="learning rate default is wrong",
        evidence=["observed default 0.001"],
        related_files=["train.py"],
        confidence=0.9,
    )


def _experience(identifier: str = "exp-1") -> RepairExperience:
    return RepairExperience(
        id=identifier,
        category="configuration",
        error_signature="wrong learning rate default 0.001",
        stack_tags=("python", "train.py"),
        root_cause="learning rate default is wrong",
        failed_diffs=(),
        verified_diff="diff --git a/train.py b/train.py\n",
        probe_summary="2/2 stages passed",
        repository_url="https://example.test/source.git",
        commit_sha="a" * 40,
        model="test-model",
        created_at="2026-09-17T00:00:00Z",
    )


def test_verified_experience_round_trips_and_excludes_current_repository(
    tmp_path: Path,
) -> None:
    memory = SQLiteRepairMemory(tmp_path / "memory.sqlite3")
    memory.record_verified(_experience())

    found = memory.retrieve(
        _diagnosis(), repository_url="https://other.test/repo.git", commit_sha="b" * 40
    )
    excluded = memory.retrieve(
        _diagnosis(),
        repository_url="https://example.test/source.git",
        commit_sha="a" * 40,
    )

    assert found == (_experience(),)
    assert excluded == ()


def test_memory_rejects_unverified_or_secret_bearing_experience(tmp_path: Path) -> None:
    memory = SQLiteRepairMemory(tmp_path / "memory.sqlite3")

    with pytest.raises(ValueError, match="verified"):
        memory.record_verified(replace(_experience(), probe_passed=False))
    with pytest.raises(ValueError, match="credential"):
        memory.record_verified(
            replace(_experience("secret"), error_signature="Bearer abcdefghijklmnop")
        )


def test_retrieval_ranks_matching_terms_and_is_deterministic(tmp_path: Path) -> None:
    memory = SQLiteRepairMemory(tmp_path / "memory.sqlite3")
    memory.record_verified(
        replace(
            _experience("weak"),
            error_signature="unrelated configuration",
            created_at="2026-09-17T00:00:00Z",
        )
    )
    memory.record_verified(
        replace(
            _experience("strong"),
            error_signature="learning rate default 0.001 train.py",
            created_at="2026-09-17T00:00:01Z",
        )
    )

    found = memory.retrieve(
        _diagnosis(),
        repository_url="https://other.test/repo.git",
        commit_sha="b" * 40,
        top_k=2,
    )

    assert [item.id for item in found] == ["strong", "weak"]


def test_null_memory_and_context_bounds() -> None:
    memory = NullRepairMemory()
    assert memory.retrieve(
        _diagnosis(), repository_url="repo", commit_sha="sha"
    ) == ()

    context = build_repair_context(
        current_failure="x" * 20_000,
        diagnosis=_diagnosis(),
        allowed_paths=("train.py",),
        previous_patch=None,
        verification_failure="failed probe",
        rollback_complete=True,
        experiences=(_experience(),),
    )

    assert "...<truncated>..." in context
    assert "ROLLBACK_STATUS\ncomplete" in context
    assert "RETRIEVED_VERIFIED_EXPERIENCES" in context
    assert "verified_diff=" in context


def test_sqlite_memory_releases_windows_file_handle() -> None:
    with TemporaryDirectory() as temporary:
        path = Path(temporary) / "memory.sqlite3"
        memory = SQLiteRepairMemory(path)
        memory.record_verified(_experience())
        assert memory.retrieve(
            _diagnosis(), repository_url="other", commit_sha="b" * 40
        )

    assert not Path(temporary).exists()
