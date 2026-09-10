from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated

import typer
from openai import OpenAI
from pydantic import ValidationError

from repropilot.artifacts import ArtifactStore
from repropilot.domain import ApprovalDecision, RunStatus
from repropilot.orchestrator import ReproPilot
from repropilot.paper import OpenAICompatiblePaperLLM
from repropilot.services import DefaultRunServices, OpenAICompatiblePatchGenerator
from repropilot.settings import load_run_request

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, readable=True),
    ],
    output_root: Annotated[Path, typer.Option()] = Path("runs"),
    validate_only: Annotated[bool, typer.Option()] = False,
) -> None:
    """Execute a bounded reproduction run, or only validate its configuration."""
    try:
        request = load_run_request(config)
    except (OSError, ValueError, ValidationError) as exc:
        typer.echo(f"Invalid configuration: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    if validate_only:
        store = ArtifactStore.create(output_root, request)
        typer.echo(f"Validated configuration and created run: {store.run_dir}")
        return

    try:
        services = _default_services()
        summary = ReproPilot(output_root, services).run(request)
    except (OSError, ValueError, RuntimeError) as exc:
        typer.echo(f"Cannot start run: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Run: {summary.run_dir}")
    typer.echo(f"Status: {summary.status.value}")
    if (summary.run_dir / "report.html").exists():
        typer.echo(f"Report: {summary.run_dir / 'report.html'}")
    if summary.status not in {RunStatus.SUCCEEDED, RunStatus.WAITING_APPROVAL}:
        raise typer.Exit(code=1)


@app.command("inspect")
def inspect_run(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Print the current status and evidence-event count for a run."""
    store = ArtifactStore(run_dir)
    metadata = json.loads(store.run_path.read_text(encoding="utf-8"))
    typer.echo(f"Run: {metadata['run_id']}")
    typer.echo(f"Status: {metadata['status']}")
    typer.echo(f"Events: {len(store.read_events())}")


@app.command()
def approve(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    patch_id: Annotated[str, typer.Argument()],
) -> None:
    """Record approval for the exact pending patch bytes."""
    _record_approval(run_dir, patch_id, approved=True, reason=None)
    typer.echo(f"Approved patch: {patch_id}")


@app.command()
def reject(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    patch_id: Annotated[str, typer.Argument()],
    reason: Annotated[str, typer.Option(min=1)],
) -> None:
    """Reject a pending patch and record the reason."""
    _record_approval(run_dir, patch_id, approved=False, reason=reason)
    typer.echo(f"Rejected patch: {patch_id}")


@app.command()
def resume(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
) -> None:
    """Resume a paused run using the recorded approval or rejection."""
    approval_path = run_dir / "approval.json"
    try:
        approval = ApprovalDecision.model_validate_json(
            approval_path.read_text(encoding="utf-8")
        )
        summary = ReproPilot(run_dir.parent, _default_services()).resume(run_dir, approval)
    except (OSError, ValueError, RuntimeError, ValidationError) as exc:
        typer.echo(f"Cannot resume run: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Status: {summary.status.value}")
    typer.echo(f"Report: {summary.run_dir / 'report.html'}")
    if summary.status is not RunStatus.SUCCEEDED:
        raise typer.Exit(code=1)


@app.command()
def serve(
    output_root: Annotated[Path, typer.Option()] = Path("runs"),
    host: Annotated[str, typer.Option(help="Loopback host only.")] = "127.0.0.1",
    port: Annotated[int, typer.Option(min=0, max=65535)] = 8765,
    static_root: Annotated[Path, typer.Option()] = Path("prototype/dist/client"),
) -> None:
    """Serve the local Web UI and real run API on 127.0.0.1."""
    from repropilot.web import LocalRunServer, OrchestratorExecutor

    assets = static_root if static_root.is_dir() else None
    try:
        server = LocalRunServer(
            host=host,
            port=port,
            output_root=output_root,
            runner=OrchestratorExecutor(output_root, _default_services),
            static_root=assets,
        )
    except (OSError, ValueError) as exc:
        typer.echo(f"Cannot start local server: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Local ReproPilot: http://{host}:{server.port}")
    if assets is None:
        typer.echo("Prototype build not found; serving the API only.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("Stopping local ReproPilot server.")
    finally:
        server.shutdown()


def _record_approval(
    run_dir: Path,
    patch_id: str,
    *,
    approved: bool,
    reason: str | None,
) -> None:
    pending_path = run_dir / "pending_patch.json"
    try:
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        typer.echo(f"Cannot read pending patch: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if pending.get("patch_id") != patch_id:
        typer.echo("Patch ID does not match the pending patch.", err=True)
        raise typer.Exit(code=2)
    decision = ApprovalDecision(
        patch_id=patch_id,
        patch_sha256=pending["patch_sha256"],
        approved=approved,
        reason=reason,
    )
    ArtifactStore(run_dir).write_json_artifact(
        "approval.json", decision.model_dump(mode="json")
    )


def _default_services() -> DefaultRunServices:
    api_key = os.environ.get("OPENAI_API_KEY")
    model = os.environ.get("OPENAI_MODEL")
    if not api_key or not model:
        raise RuntimeError(
            "OPENAI_API_KEY and OPENAI_MODEL are required; use --validate-only to check config"
        )
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    client = OpenAI(api_key=api_key, base_url=base_url)
    structured_output_mode = (
        "json_object"
        if base_url and base_url.rstrip("/") == "https://api.deepseek.com"
        else "json_schema"
    )
    return DefaultRunServices(
        paper_llm=OpenAICompatiblePaperLLM(
            client,
            model,
            structured_output_mode=structured_output_mode,
        ),
        patch_generator=OpenAICompatiblePatchGenerator(
            client,
            model,
            structured_output_mode=structured_output_mode,
        ),
    )


if __name__ == "__main__":
    app()
