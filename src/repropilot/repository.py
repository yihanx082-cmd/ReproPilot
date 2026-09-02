from __future__ import annotations

import ast
import json
import re
import tomllib
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from yaml.nodes import MappingNode, Node, ScalarNode

from repropilot.artifacts import ArtifactStore
from repropilot.domain import RepoFact, RunRequest

MAX_FILE_SIZE = 1024 * 1024
IGNORED_DIRECTORIES = {".git", ".venv", "data", "venv", "weights"}
SUPPORTED_CONFIG_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}

FIELD_ALIASES = {
    "arch": "model.architecture",
    "batch_size": "training.batch_size",
    "epochs": "training.epochs",
    "learning_rate": "optimizer.learning_rate",
    "lr": "optimizer.learning_rate",
    "momentum": "optimizer.momentum",
    "seed": "training.seed",
    "weight_decay": "optimizer.weight_decay",
}

COMMAND_FIELD_FLAGS = {
    "--arch": "model.architecture",
    "--epochs": "training.epochs",
    "--batch-size": "training.batch_size",
    "--lr": "optimizer.learning_rate",
    "--learning-rate": "optimizer.learning_rate",
    "--momentum": "optimizer.momentum",
    "--weight-decay": "optimizer.weight_decay",
    "--seed": "training.seed",
}


def scan_repository(
    path: Path, *, store: ArtifactStore | None = None
) -> list[RepoFact]:
    root = path.resolve()
    if not root.is_dir():
        raise ValueError(f"Repository path is not a directory: {root}")

    facts: list[RepoFact] = []
    for file_path in _repository_files(root):
        suffix = file_path.suffix.lower()
        if suffix in {".yaml", ".yml"}:
            facts.extend(_scan_yaml(root, file_path))
        elif suffix == ".json":
            facts.extend(_scan_mapping_file(root, file_path, "json"))
        elif suffix == ".toml":
            facts.extend(_scan_mapping_file(root, file_path, "toml"))
        elif suffix == ".py":
            facts.extend(_scan_python(root, file_path))
        elif suffix == ".md" and file_path.name.lower().startswith("readme"):
            facts.extend(_scan_readme(root, file_path))

    facts = sorted(facts, key=lambda fact: (fact.source_path, fact.line_start, fact.field))
    if store is not None:
        store.write_json_artifact(
            "repo_facts.json",
            [fact.model_dump(mode="json") for fact in facts],
        )
    return facts


def execution_request_facts(request: RunRequest) -> list[RepoFact]:
    facts = [
        RepoFact(
            field="dataset.name",
            value=request.dataset.name,
            source_path="run-request.dataset",
            line_start=1,
            extractor="run_request",
        )
    ]
    seen = {"dataset.name"}
    commands = [("run-request.command", request.command)]
    if request.formal_experiment is not None:
        commands.append(
            ("run-request.formal_experiment.command", request.formal_experiment.command)
        )
    for source_path, command in commands:
        for index, flag in enumerate(command[:-1]):
            field = COMMAND_FIELD_FLAGS.get(flag)
            if field is None or field in seen:
                continue
            raw_value: object = command[index + 1]
            if raw_value == "{seed}" and request.formal_experiment is not None:
                raw_value = request.formal_experiment.seeds
            facts.append(
                RepoFact(
                    field=field,
                    value=_coerce_cli_value(raw_value),
                    source_path=source_path,
                    line_start=index + 1,
                    extractor="run_request",
                )
            )
            seen.add(field)
    return facts


def _coerce_cli_value(value: object) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def _repository_files(root: Path) -> Iterator[Path]:
    for file_path in root.rglob("*"):
        relative_parts = file_path.relative_to(root).parts
        if any(part.lower() in IGNORED_DIRECTORIES for part in relative_parts[:-1]):
            continue
        if not file_path.is_file() or file_path.stat().st_size > MAX_FILE_SIZE:
            continue
        if file_path.suffix.lower() in SUPPORTED_CONFIG_SUFFIXES | {".md", ".py"}:
            yield file_path


def _scan_yaml(root: Path, file_path: Path) -> list[RepoFact]:
    text = file_path.read_text(encoding="utf-8")
    document = yaml.compose(text, Loader=yaml.SafeLoader)
    if document is None:
        return []

    facts: list[RepoFact] = []

    def visit(node: Node, prefix: tuple[str, ...] = ()) -> None:
        if not isinstance(node, MappingNode):
            return
        for key_node, value_node in node.value:
            if not isinstance(key_node, ScalarNode):
                continue
            path = (*prefix, str(key_node.value))
            if isinstance(value_node, MappingNode):
                visit(value_node, path)
            elif isinstance(value_node, ScalarNode):
                value = yaml.safe_load(value_node.value)
                facts.append(
                    RepoFact(
                        field=_canonical_field(".".join(path)),
                        value=value,
                        source_path=file_path.relative_to(root).as_posix(),
                        line_start=key_node.start_mark.line + 1,
                        extractor="yaml",
                    )
                )

    visit(document)
    return facts


def _scan_mapping_file(
    root: Path, file_path: Path, extractor: Literal["json", "toml"]
) -> list[RepoFact]:
    text = file_path.read_text(encoding="utf-8")
    parsed = json.loads(text) if extractor == "json" else tomllib.loads(text)
    if not isinstance(parsed, Mapping):
        return []

    facts: list[RepoFact] = []
    for field, value in _flatten(parsed):
        if not _is_json_value(value):
            continue
        leaf_key = field.rsplit(".", 1)[-1]
        facts.append(
            RepoFact(
                field=_canonical_field(field),
                value=value,
                source_path=file_path.relative_to(root).as_posix(),
                line_start=_find_key_line(text, leaf_key),
                extractor=extractor,
            )
        )
    return facts


def _flatten(
    mapping: Mapping[str, Any], prefix: tuple[str, ...] = ()
) -> Iterator[tuple[str, Any]]:
    for key, value in mapping.items():
        path = (*prefix, str(key))
        if isinstance(value, Mapping):
            yield from _flatten(value, path)
        else:
            yield ".".join(path), value


def _find_key_line(text: str, key: str) -> int:
    pattern = re.compile(rf"(?:[\"']?{re.escape(key)}[\"']?)\s*[:=]")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            return line_number
    return 1


def _scan_python(root: Path, file_path: Path) -> list[RepoFact]:
    text = file_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(file_path))
    facts: list[RepoFact] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        try:
            flag = ast.literal_eval(node.args[0])
        except (ValueError, TypeError):
            continue
        if not isinstance(flag, str) or not flag.startswith("--"):
            continue
        default_node = next(
            (keyword.value for keyword in node.keywords if keyword.arg == "default"),
            None,
        )
        if default_node is None:
            continue
        try:
            default = ast.literal_eval(default_node)
        except (ValueError, TypeError):
            continue
        if not _is_json_value(default):
            continue
        facts.append(
            RepoFact(
                field=_canonical_field(flag.removeprefix("--").replace("-", "_")),
                value=default,
                source_path=file_path.relative_to(root).as_posix(),
                line_start=node.lineno,
                extractor="python_ast",
            )
        )
    return facts


def _scan_readme(root: Path, file_path: Path) -> list[RepoFact]:
    facts: list[RepoFact] = []
    command_pattern = re.compile(r"\bpython(?:3)?\s+([^\s`]+\.py)\b", re.IGNORECASE)
    for line_number, line in enumerate(
        file_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        for match in command_pattern.finditer(line):
            script = match.group(1).replace("\\", "/")
            if not (file_path.parent / script).is_file() and not (root / script).is_file():
                facts.append(
                    RepoFact(
                        field="readme.missing_script",
                        value=script,
                        source_path=file_path.relative_to(root).as_posix(),
                        line_start=line_number,
                        extractor="readme",
                    )
                )
    return facts


def _canonical_field(field: str) -> str:
    normalized = field.lower().replace("-", "_")
    return FIELD_ALIASES.get(normalized, normalized)


def _is_json_value(value: Any) -> bool:
    if value is None or isinstance(value, str | int | float | bool):
        return True
    if isinstance(value, list):
        return all(_is_json_value(item) for item in value)
    return False
