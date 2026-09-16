from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from repropilot.domain import Diagnosis

_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")
_SECRET_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9]{12,}|gho_[A-Za-z0-9]{12,}|github_pat_[A-Za-z0-9_]+|Bearer\s+\S+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RepairExperience:
    id: str
    category: str
    error_signature: str
    stack_tags: tuple[str, ...]
    root_cause: str
    failed_diffs: tuple[str, ...]
    verified_diff: str
    probe_summary: str
    repository_url: str
    commit_sha: str
    model: str
    created_at: str
    probe_passed: bool = True
    scope_compliant: bool = True


class RepairMemory(Protocol):
    def retrieve(
        self,
        diagnosis: Diagnosis,
        *,
        repository_url: str,
        commit_sha: str,
        top_k: int = 2,
    ) -> tuple[RepairExperience, ...]: ...

    def record_verified(self, experience: RepairExperience) -> None: ...


class NullRepairMemory:
    def retrieve(
        self,
        diagnosis: Diagnosis,
        *,
        repository_url: str,
        commit_sha: str,
        top_k: int = 2,
    ) -> tuple[RepairExperience, ...]:
        del diagnosis, repository_url, commit_sha, top_k
        return ()

    def record_verified(self, experience: RepairExperience) -> None:
        del experience


class SQLiteRepairMemory:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS repair_experiences (
                    id TEXT PRIMARY KEY,
                    category TEXT NOT NULL,
                    error_signature TEXT NOT NULL,
                    stack_tags TEXT NOT NULL,
                    root_cause TEXT NOT NULL,
                    failed_diffs TEXT NOT NULL,
                    verified_diff TEXT NOT NULL,
                    probe_summary TEXT NOT NULL,
                    repository_url TEXT NOT NULL,
                    commit_sha TEXT NOT NULL,
                    model TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    probe_passed INTEGER NOT NULL,
                    scope_compliant INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS repair_experiences_category
                    ON repair_experiences(category);
                """
            )
            existing = connection.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if existing is None:
                connection.execute("INSERT INTO schema_version(version) VALUES (1)")
            elif int(existing["version"]) != 1:
                raise RuntimeError("Unsupported repair memory schema version")

    def record_verified(self, experience: RepairExperience) -> None:
        if not experience.probe_passed or not experience.scope_compliant:
            raise ValueError("Only verified, scope-compliant repairs can enter memory")
        _reject_secrets(experience)
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO repair_experiences (
                    id, category, error_signature, stack_tags, root_cause,
                    failed_diffs, verified_diff, probe_summary, repository_url,
                    commit_sha, model, created_at, probe_passed, scope_compliant
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experience.id,
                    experience.category,
                    experience.error_signature,
                    "\n".join(experience.stack_tags),
                    experience.root_cause,
                    "\x1e".join(experience.failed_diffs),
                    experience.verified_diff,
                    experience.probe_summary,
                    experience.repository_url,
                    experience.commit_sha,
                    experience.model,
                    experience.created_at,
                    int(experience.probe_passed),
                    int(experience.scope_compliant),
                ),
            )

    def retrieve(
        self,
        diagnosis: Diagnosis,
        *,
        repository_url: str,
        commit_sha: str,
        top_k: int = 2,
    ) -> tuple[RepairExperience, ...]:
        if top_k < 1:
            return ()
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT * FROM repair_experiences
                WHERE category = ?
                  AND NOT (repository_url = ? AND commit_sha = ?)
                  AND probe_passed = 1
                  AND scope_compliant = 1
                """,
                (diagnosis.category.value, repository_url, commit_sha),
            ).fetchall()
        query_tokens = _tokens(
            " ".join([diagnosis.root_cause, *diagnosis.evidence, *diagnosis.related_files])
        )
        experiences = [_row_to_experience(row) for row in rows]

        def ranking(experience: RepairExperience) -> tuple[int, str, str]:
            candidate_tokens = _tokens(
                " ".join(
                    [
                        experience.error_signature,
                        *experience.stack_tags,
                        experience.root_cause,
                    ]
                )
            )
            return (-len(query_tokens & candidate_tokens), experience.created_at, experience.id)

        return tuple(sorted(experiences, key=ranking)[:top_k])


def build_repair_context(
    *,
    current_failure: str,
    diagnosis: Diagnosis | None,
    allowed_paths: tuple[str, ...],
    previous_patch: str | None,
    verification_failure: str | None,
    rollback_complete: bool,
    experiences: tuple[RepairExperience, ...],
) -> str:
    diagnosis_text = "none"
    if diagnosis is not None:
        diagnosis_text = "\n".join(
            [
                f"category={diagnosis.category.value}",
                f"root_cause={diagnosis.root_cause}",
                "evidence=" + " | ".join(diagnosis.evidence),
                "related_files=" + ", ".join(diagnosis.related_files),
            ]
        )
    experience_text = "none"
    if experiences:
        rendered: list[str] = []
        for index, experience in enumerate(experiences, start=1):
            rendered.append(
                _bounded(
                    "\n".join(
                        [
                            f"experience={index}",
                            f"category={experience.category}",
                            f"error_signature={experience.error_signature}",
                            f"root_cause={experience.root_cause}",
                            f"verified_diff={experience.verified_diff}",
                            f"probe_summary={experience.probe_summary}",
                        ]
                    ),
                    4_000,
                )
            )
        experience_text = "\n\n".join(rendered)
    return "\n\n".join(
        [
            "CURRENT_FAILURE\n" + _bounded(current_failure, 12_000),
            "STRUCTURED_DIAGNOSIS\n" + diagnosis_text,
            "ALLOWED_PATHS\n" + ("\n".join(allowed_paths) or "none"),
            "PREVIOUS_PATCH\n" + _bounded(previous_patch or "none", 12_000),
            "VERIFICATION_FAILURE\n"
            + _bounded(verification_failure or "none", 8_000),
            "ROLLBACK_STATUS\n" + ("complete" if rollback_complete else "none"),
            "RETRIEVED_VERIFIED_EXPERIENCES\n" + experience_text,
        ]
    )


def _bounded(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    marker = "\n...<truncated>...\n"
    side = (limit - len(marker)) // 2
    return value[:side] + marker + value[-side:]


def _tokens(value: str) -> set[str]:
    return set(_TOKEN_PATTERN.findall(value.casefold()))


def _reject_secrets(experience: RepairExperience) -> None:
    values = [
        experience.error_signature,
        *experience.stack_tags,
        experience.root_cause,
        *experience.failed_diffs,
        experience.verified_diff,
        experience.probe_summary,
        experience.repository_url,
        experience.model,
    ]
    if any(_SECRET_PATTERN.search(value) for value in values):
        raise ValueError("Repair experience contains a credential-shaped value")


def _row_to_experience(row: sqlite3.Row) -> RepairExperience:
    return RepairExperience(
        id=str(row["id"]),
        category=str(row["category"]),
        error_signature=str(row["error_signature"]),
        stack_tags=tuple(filter(None, str(row["stack_tags"]).splitlines())),
        root_cause=str(row["root_cause"]),
        failed_diffs=tuple(filter(None, str(row["failed_diffs"]).split("\x1e"))),
        verified_diff=str(row["verified_diff"]),
        probe_summary=str(row["probe_summary"]),
        repository_url=str(row["repository_url"]),
        commit_sha=str(row["commit_sha"]),
        model=str(row["model"]),
        created_at=str(row["created_at"]),
        probe_passed=bool(row["probe_passed"]),
        scope_compliant=bool(row["scope_compliant"]),
    )
