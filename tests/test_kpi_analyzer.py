import numpy as np
import pandas as pd

from src.services.kpi_analyzer import assess, assess_frame, percentile_rank, severity
from src.utils.schema import CATEGORIES, NORMAL, SEVERITY_KPIS


def test_band_edges_higher_is_worse(sample_baselines):
    th = sample_baselines.thresholds["latency_ms"]
    vals = np.array([th["degraded"] - 0.001, th["degraded"], th["critical"] - 0.001, th["critical"]])
    assert severity(vals, "latency_ms", sample_baselines).tolist() == [0, 1, 1, 2]


def test_band_edges_lower_is_worse(sample_baselines):
    th = sample_baselines.thresholds["throughput_mbps"]
    vals = np.array([th["degraded"] + 0.001, th["degraded"], th["critical"] + 0.001, th["critical"]])
    assert severity(vals, "throughput_mbps", sample_baselines).tolist() == [0, 1, 1, 2]


def test_ties_use_mid_rank():
    # Half the table is zero (like call drop rate): zero should rank near the middle of the ties, not at 50%+.
    table = [0.0] * 500 + list(np.linspace(0.1, 5, 501))
    assert percentile_rank(np.array([0.0]), table)[0] < 0.3


def test_bad_snapshot_classifies_as_transport(sample_baselines):
    b = sample_baselines
    kpis = {k: b.median(k) for k in SEVERITY_KPIS}
    kpis.update(latency_ms=b.quantiles["latency_ms"]["p95"], jitter_ms=b.quantiles["jitter_ms"]["p95"],
                packet_loss_pct=b.quantiles["packet_loss_pct"]["p95"], weather="Clear",
                temperature_c=b.median("temperature_c"), humidity_pct=b.median("humidity_pct"))
    a = assess(kpis, b)
    assert a["primary_category"] == "TRANSPORT_QOS"
    assert set(a["symptoms"]) >= {"high_latency", "high_jitter", "high_packet_loss"}
    assert a["anomalies"][0]["band"] == "critical"


def test_median_snapshot_is_normal_and_imputation_reported(sample_baselines):
    a = assess({}, sample_baselines)
    assert a["primary_category"] == NORMAL
    assert len(a["imputed_fields"]) == 21 and a["anomalies"] == []


def test_single_assess_matches_frame_assess(sample_cases, sample_baselines):
    row = sample_cases.iloc[123]
    single = assess(row.to_dict(), sample_baselines)
    frame = assess_frame(sample_cases.iloc[[123]], sample_baselines).iloc[0]
    assert single["primary_category"] == frame["primary_category"]
    assert single["category_scores"] == {c: round(float(frame[f"score_{c}"]), 3) for c in CATEGORIES}


def test_category_distribution_is_balanced(sample_cases, sample_baselines):
    dist = assess_frame(sample_cases, sample_baselines)["primary_category"].value_counts(normalize=True)
    cats = dist.drop(NORMAL, errors="ignore")
    assert cats.min() > 0.05 and cats.max() < 0.25
    assert isinstance(dist, pd.Series)
