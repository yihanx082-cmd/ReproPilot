from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest


def _docker_contracts():
    try:
        from repropilot.sandbox import DockerSandbox
    except (ImportError, ModuleNotFoundError) as exc:
        pytest.fail(f"Task 4 Docker sandbox is not implemented: {exc}")
    return DockerSandbox


def _docker_binary() -> str:
    configured = os.environ.get("REPROPILOT_DOCKER_BIN")
    discovered = shutil.which("docker")
    if configured:
        return configured
    if discovered:
        return discovered
    pytest.fail("Docker integration tests require REPROPILOT_DOCKER_BIN or docker on PATH")


pytestmark = pytest.mark.skipif(
    os.environ.get("REPROPILOT_DOCKER_TESTS") != "1",
    reason="set REPROPILOT_DOCKER_TESTS=1 to run Docker integration tests",
)


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Any]:
    DockerSandbox = _docker_contracts()
    root = tmp_path_factory.mktemp("docker-sandbox")
    source = root / "source"
    shutil.copytree(Path(__file__).parent / "fixtures" / "docker_project", source)
    worktree = root / "worktree"
    shutil.copytree(source, worktree)
    dataset = root / "dataset"
    dataset.mkdir()
    (dataset / "sample.txt").write_text("input", encoding="utf-8")
    image_tag = f"repropilot-test-{uuid4().hex[:12]}"
    instance = DockerSandbox(
        worktree=worktree,
        source=source,
        dataset=dataset,
        logs_dir=root / "logs",
        image_tag=image_tag,
        docker_executable=_docker_binary(),
        secrets=["TOP_SECRET"],
    )
    build = instance.build(source, image_tag)
    assert build.exit_code == 0, build.stderr_path.read_text(encoding="utf-8")
    assert build.image_digest.startswith("sha256:")
    assert build.dockerfile_sha256
    yield instance
    subprocess.run(
        [_docker_binary(), "image", "rm", "--force", image_tag],
        check=False,
        capture_output=True,
        shell=False,
    )


def test_terminates_a_command_at_its_timeout(sandbox: Any):
    result = sandbox.run(
        ["python", "-c", "import time; time.sleep(10)"],
        timeout=1,
    )

    assert result.timed_out
    assert result.exit_code == 124
    assert result.duration_seconds < 5


@pytest.mark.parametrize("mount", ["source", "dataset"])
def test_mounts_original_inputs_read_only(sandbox: Any, mount: str):
    result = sandbox.run(
        [
            "python",
            "-c",
            f"from pathlib import Path; Path('/{mount}/blocked.txt').write_text('bad')",
        ],
        timeout=10,
    )

    assert result.exit_code != 0
    assert not (getattr(sandbox, mount) / "blocked.txt").exists()


def test_mounts_the_cloned_worktree_writable_and_redacts_logs(sandbox: Any):
    result = sandbox.run(
        [
            "python",
            "-c",
            "from pathlib import Path; Path('generated.txt').write_text('ok'); print('TOP_SECRET')",
        ],
        timeout=10,
    )

    assert result.exit_code == 0
    assert (sandbox.worktree / "generated.txt").read_text(encoding="utf-8") == "ok"
    assert "TOP_SECRET" not in result.stdout_path.read_text(encoding="utf-8")
    assert "[REDACTED]" in result.stdout_path.read_text(encoding="utf-8")
    assert "TOP_SECRET" not in " ".join(result.argv)
