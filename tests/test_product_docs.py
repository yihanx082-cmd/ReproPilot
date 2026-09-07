from pathlib import Path

PRODUCT_DOCS = Path(__file__).parents[1] / "docs" / "product"


def test_research_kit_has_required_sections() -> None:
    interview = (PRODUCT_DOCS / "interview-kit.md").read_text(encoding="utf-8")
    records = (PRODUCT_DOCS / "research-records" / "README.md").read_text(
        encoding="utf-8"
    )
    findings = (PRODUCT_DOCS / "research-findings.md").read_text(encoding="utf-8")
    for heading in ["Round One", "Round Two", "Consent", "Anonymization"]:
        assert heading in interview
    for participant in ["P01", "P02", "P03", "P04", "P05"]:
        assert participant in records
    assert "Awaiting real participant responses" in findings
    assert "statistically representative" in findings


def test_metrics_and_usability_are_measurable() -> None:
    metrics = (PRODUCT_DOCS / "metrics-plan.md").read_text(encoding="utf-8")
    usability = (PRODUCT_DOCS / "usability-test.md").read_text(encoding="utf-8")
    for metric in [
        "Task completion rate",
        "Time to interpret",
        "Manual steps reduced",
        "Decision correctness",
        "Report comprehension",
        "Satisfaction",
    ]:
        assert metric in metrics
    assert "4 of 5" in usability
    assert "credibility score" in usability
    assert "model accuracy" in usability
