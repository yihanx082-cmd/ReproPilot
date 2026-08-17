from __future__ import annotations

import hashlib
import subprocess
import time
from pathlib import Path
from uuid import uuid4

from repropilot.domain import CommandResult

TIMEOUT_EXIT_CODE = 124


class DockerSandbox:
    def __init__(
        self,
        *,
        worktree: Path,
        source: Path,
        dataset: Path,
        logs_dir: Path,
        image_tag: str,
        docker_executable: str = "docker",
        secrets: list[str] | None = None,
        memory: str = "2g",
        cpus: float = 2.0,
    ) -> None:
        self.worktree = worktree.resolve()
        self.source = source.resolve()
        self.dataset = dataset.resolve()
        self.logs_dir = logs_dir.resolve()
        self.image_tag = image_tag
        self.docker_executable = docker_executable
        self.secrets = [secret for secret in (secrets or []) if secret]
        self.memory = memory
        self.cpus = cpus
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._command_number = 0

    def build(
        self, context: Path, image_tag: str, timeout: float = 1200
    ) -> CommandResult:
        context = context.resolve()
        dockerfile = context / "Dockerfile"
        dockerfile_sha256 = hashlib.sha256(dockerfile.read_bytes()).hexdigest()
        self.image_tag = image_tag
        argv = [self.docker_executable, "build", "--tag", image_tag, str(context)]
        result = self._execute(argv, timeout=timeout, label="build")
        digest = None
        if result.exit_code == 0:
            inspection = subprocess.run(
                [
                    self.docker_executable,
                    "image",
                    "inspect",
                    image_tag,
                    "--format",
                    "{{.Id}}",
                ],
                capture_output=True,
                check=False,
                shell=False,
                text=True,
            )
            if inspection.returncode == 0:
                digest = inspection.stdout.strip() or None
        return result.model_copy(
            update={
                "image_digest": digest,
                "dockerfile_sha256": dockerfile_sha256,
            }
        )

    def run(
        self,
        argv: list[str],
        timeout: float,
        network: bool = False,
    ) -> CommandResult:
        if not argv:
            raise ValueError("Container command argv must not be empty")
        container_name = f"repropilot-{uuid4().hex[:16]}"
        docker_argv = [
            self.docker_executable,
            "run",
            "--rm",
            "--name",
            container_name,
            "--memory",
            self.memory,
            "--cpus",
            str(self.cpus),
            "--pids-limit",
            "256",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65532:65532",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=64m",
            "--mount",
            self._mount(self.worktree, "/workspace", read_only=False),
            "--mount",
            self._mount(self.source, "/source", read_only=True),
            "--mount",
            self._mount(self.dataset, "/dataset", read_only=True),
            "--workdir",
            "/workspace",
        ]
        if not network:
            docker_argv.extend(["--network", "none"])
        docker_argv.extend([self.image_tag, *argv])
        return self._execute(
            docker_argv,
            timeout=timeout,
            label="run",
            container_name=container_name,
            reported_argv=argv,
        )

    def _execute(
        self,
        argv: list[str],
        *,
        timeout: float,
        label: str,
        container_name: str | None = None,
        reported_argv: list[str] | None = None,
    ) -> CommandResult:
        self._command_number += 1
        prefix = f"{self._command_number:03d}-{label}"
        stdout_path = self.logs_dir / f"{prefix}.stdout.log"
        stderr_path = self.logs_dir / f"{prefix}.stderr.log"
        started = time.perf_counter()
        timed_out = False
        try:
            completed = subprocess.run(
                argv,
                capture_output=True,
                check=False,
                shell=False,
                text=True,
                timeout=timeout,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = TIMEOUT_EXIT_CODE
            stdout = self._timeout_text(exc.stdout)
            stderr = self._timeout_text(exc.stderr)
            if container_name is not None:
                subprocess.run(
                    [self.docker_executable, "rm", "--force", container_name],
                    capture_output=True,
                    check=False,
                    shell=False,
                    text=True,
                    timeout=30,
                )

        duration = time.perf_counter() - started
        stdout_path.write_text(self._redact(stdout), encoding="utf-8")
        stderr_path.write_text(self._redact(stderr), encoding="utf-8")
        visible_argv = reported_argv if reported_argv is not None else argv
        return CommandResult(
            exit_code=exit_code,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            duration_seconds=duration,
            timed_out=timed_out,
            argv=[self._redact(argument) for argument in visible_argv],
        )

    @staticmethod
    def _mount(path: Path, target: str, *, read_only: bool) -> str:
        options = f"type=bind,source={path},target={target}"
        return f"{options},readonly" if read_only else options

    @staticmethod
    def _timeout_text(value: str | bytes | None) -> str:
        if value is None:
            return ""
        return value.decode(errors="replace") if isinstance(value, bytes) else value

    def _redact(self, value: str) -> str:
        redacted = value
        for secret in self.secrets:
            redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
