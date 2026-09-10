import json
from pathlib import Path

FIXTURE = Path(__file__).parents[1] / "prototype" / "data" / "demo-run.json"


def test_demo_fixture_is_realistic_and_sanitized() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["meta"]["demo"] is True
    assert "ResNet-20" in payload["meta"]["source_label"]
    assert payload["report"]["score"] == 80
    assert payload["report"]["label"] == "PARTIAL"
    assert payload["report"]["comparison"]["paper_value"] == 8.75
    assert payload["report"]["comparison"]["observed_mean"] == 8.27
    assert len(payload["report"]["dimensions"]) == 7
    assert payload["approval"]["risk"] == "high"
    assert payload["approval"]["example"] == "91.73% accuracy → 8.27% error"
    assert "table 6" in payload["approval"]["paper_evidence"].lower()
    assert payload["approval"]["targeted_test_result"]["exit_code"] == 0
    assert payload["approval"]["targeted_test_result"]["assertion"]
    assert payload["approval"]["targeted_test_result"]["log_excerpt"]
    serialized = json.dumps(payload).lower()
    for forbidden in ["openai_api_key", "sk-", "c:\\users", "d:\\"]:
        assert forbidden not in serialized
