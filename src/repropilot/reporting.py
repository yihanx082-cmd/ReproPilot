from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from repropilot.domain import EvidenceBundle
from repropilot.scoring import score_reproduction


def render_report(bundle: EvidenceBundle, output: Path) -> Path:
    template_dir = Path(__file__).with_name("templates")
    environment = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    template = environment.get_template("report.html.j2")
    score = score_reproduction(bundle)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(template.render(bundle=bundle, score=score), encoding="utf-8")
    return output
