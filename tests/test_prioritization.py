import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.services.analytics import segment_stats
from src.services.impact import estimate_impact
from src.services.kpi_analyzer import Baselines, assess
from src.services.ml.predictor import Predictor
from src.services.prioritization import prioritize, prioritize_frame
from src.utils.config import get_settings

ART = get_settings().artifacts_dir
SCENARIOS = json.loads((Path(__file__).parent / "test_cases" / "priority_scenarios.json").read_text(encoding="utf-8"))
LEVELS = ["P1", "P2", "P3", "P4"]


@pytest.fixture(scope="module")
def env():
    if not (ART / "processed" / "cases.parquet").exists():
        pytest.skip("artifacts missing; run preprocessing, training and prioritization")
    b = Baselines.from_json(ART / "baselines.json")
    if not b.priority:
        pytest.skip("priority not calibrated; run python -m src.services.prioritization")
    return b, Predictor(ART / "models", b), pd.read_parquet(ART / "processed" / "cases.parquet")


def run(kpis, b, predictor):
    a = assess(kpis, b)
    return prioritize(a, predictor.predict_fault_risk(kpis)["probability"], b), a


def test_corpus_priority_mix(env):
    _, _, cases = env
    mix = cases["priority"].value_counts(normalize=True)
    for lvl, target in {"P1": 0.05, "P2": 0.20, "P3": 0.40, "P4": 0.35}.items():
        assert abs(mix[lvl] - target) < 0.01


def test_scenarios_exact_and_within_one_level(env):
    b, predictor, _ = env
    exact, results = 0, []
    for s in SCENARIOS:
        level = run(s["kpis"], b, predictor)[0]["level"]
        results.append((s["id"], s["expected_priority"], level))
        exact += level == s["expected_priority"]
        assert abs(LEVELS.index(level) - LEVELS.index(s["expected_priority"])) <= 1, results
    assert exact >= 5, results  # >= 80% exact (5 of 6)


def test_single_snapshot_matches_stored_label(env):
    b, _, cases = env
    row = cases.iloc[4242]
    stored = row["priority"]
    single = prioritize(assess(row.to_dict(), b), float(row["fault_risk_prob"]), b)
    assert single["level"] == stored


def test_override_escalates_to_at_least_p2(env):
    b, predictor, _ = env
    p, _ = run(SCENARIOS[2]["kpis"], b, predictor)  # critical availability
    assert p["level"] in {"P1", "P2"} and p["overrides"]


def test_impact_levels(env):
    b, _, _ = env
    assert estimate_impact(assess({}, b), b)["level"] == "Low"
    storm = estimate_impact(assess(SCENARIOS[1]["kpis"], b), b)
    assert storm["level"] == "Severe" and storm["affected_services"] == ["all services"]


def test_segment_lift_finds_known_relationship(env):
    _, _, cases = env
    stats = segment_stats(cases, cases["sym_high_critical_alarms"].to_numpy(), exclude_symptoms=("high_critical_alarms",))
    lift = {d["factor"]: d["lift"] for d in stats["top_lifts"]}
    assert lift.get("low_throughput", 0) > 2.5  # measured ~3.2 in planning
    assert stats["count"] == int(cases["sym_high_critical_alarms"].sum())
    assert segment_stats(cases, np.zeros(len(cases), dtype=bool))["count"] == 0
