from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from repropilot.artifacts import ArtifactStore
from repropilot.domain import ApprovalDecision
from repropilot.settings import load_run_request

app = typer.Typer(no_args_is_help=True)


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option(exists=True, dir_okay=False, readable=True),
    ],
    output_root: Annotated[Path, typer.Option()] = Path("runs"),
) -> None:
    """Validate a run configuration and create its evidence directory."""
    try:
        request = load_run_request(config)
    except (OSError, ValueError, ValidationError) as exc:
        typer.echo(f"Invalid configuration: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    store = ArtifactStore.create(output_root, request)
    typer.echo(f"Created run: {store.run_dir}")


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


if __name__ == "__main__":
    app()
