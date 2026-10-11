"""tests/test_cases/sample_queries.json (plan §11.2): README/demo queries with expected structured fields only."""
import json
from pathlib import Path

CASES = Path(__file__).parent / "test_cases"
LEVELS = {"P1", "P2", "P3", "P4"}
CATEGORIES = {"CONGESTION_CAPACITY", "TRANSPORT_QOS", "RADIO_COVERAGE", "MOBILITY_HANDOVER", "AVAILABILITY_OUTAGE",
              "FAULT_ALARM", "CONFIG_CHANGE", "SECURITY_AUTH"}


def test_sample_queries_are_consistent_with_the_golden_set():
    sample = json.loads((CASES / "sample_queries.json").read_text(encoding="utf-8"))["queries"]
    golden = {q["id"]: q for q in json.loads((CASES / "golden_queries.json").read_text(encoding="utf-8"))}
    assert {"G17", "G18", "G19"} <= {q["id"] for q in sample}  # the three PRD queries
    for q in sample:
        assert q["query"] == golden[q["id"]]["query"] and q["expected_primary"] == golden[q["id"]]["expected_primary"]
        assert q["expected_primary"] in CATEGORIES and set(q["acceptable_primary"]) <= CATEGORIES
        assert q["expected_priority_range"] and set(q["expected_priority_range"]) <= LEVELS
        assert q["expected_risk_band"] in {"Low", "Medium", "High"}


def test_feedback_regressions_file_is_a_list():
    assert isinstance(json.loads((CASES / "feedback_regressions.json").read_text(encoding="utf-8")), list)
