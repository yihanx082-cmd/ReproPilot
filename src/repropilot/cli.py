from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from repropilot.artifacts import ArtifactStore
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


if __name__ == "__main__":
    app()
