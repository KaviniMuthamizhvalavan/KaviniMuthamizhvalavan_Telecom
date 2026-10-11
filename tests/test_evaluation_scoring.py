"""Evaluation-only checks (Phase 11 follow-up): the corrected scoring input and the protected baselines."""
import json
from pathlib import Path

import pytest

from evaluation.run_deepeval_rescore import case_list, corrected_output

ROOT = Path(__file__).resolve().parents[1]
GENS = ROOT / "evaluation" / "results" / "final" / "deepeval" / "generations.json"


@pytest.fixture(scope="module")
def gens():
    if not GENS.exists():
        pytest.skip("Phase 11 generations not present")
    return json.loads(GENS.read_text(encoding="utf-8"))


def test_corrected_output_adds_every_returned_case_and_keeps_the_original(gens):
    for qid, rec in gens.items():
        for system in ("A", "C", "B"):
            if system not in rec:
                continue
            out = corrected_output(rec, system)
            cases = rec["C" if system == "B" else system]["response"]["similar_cases"]
            assert cases and all(f"[{c['case_id']}]" in out for c in cases), (qid, system)
            assert out.endswith(rec[system]["actual_output"])  # original scored answer unchanged, only prefixed


def test_case_list_format():
    text = case_list([{"rank": 1, "case_id": "CASE-000001", "primary_category": "TRANSPORT_QOS", "state": "TX",
                       "season": "Winter", "weather": "Snow", "priority": "P2", "summary": "latency 150 ms (crit)"}])
    assert text.splitlines()[1] == "1. [CASE-000001] TRANSPORT_QOS | TX, Winter, Snow | priority P2 | latency 150 ms (crit)"


def test_spot_check_annotations_are_preserved():
    sheet = ROOT / "evaluation" / "results" / "final" / "components" / "manual_spot_check.csv"
    if not sheet.exists():
        pytest.skip("worksheet not present")
    import pandas as pd
    d = pd.read_csv(sheet)
    assert len(d) == 25 and d.relevant_y_n.notna().all()  # filled annotations must survive every evaluation run
